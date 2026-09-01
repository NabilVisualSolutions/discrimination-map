"""
Discrimination Map — the scraping agent.

Runs as an asyncio background task inside the FastAPI process. On each heartbeat
it polls every enabled source, geolocates what it finds, and persists new
reports. Sources are pluggable adapters; each is health-tracked so one failing
source can't take down the loop.

Source status (verified from a datacenter IP, which your VPS is):
  - Bluesky  : WORKING, no key. Public app-view searchPosts endpoint.
  - Mastodon : WORKING, no key. Public hashtag timelines across instances.
  - Reddit   : KEY-ACTIVATED. Anonymous .json is IP-blocked on cloud hosts;
               set REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET for the free OAuth API.
  - YouTube  : KEY-ACTIVATED. Set a free YOUTUBE_API_KEY.
  - X/Twitter, Instagram, TikTok : STUBBED. No free official API; scraping them
    breaks ToS and is fragile. They log a clear reason instead of pretending.

The two working sources need no configuration, so the prototype produces real,
mapped reports the moment it boots.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Callable, Optional

import httpx

import db
import geolocate
import lawref

HEARTBEAT_SECONDS = int(os.environ.get("DXMAP_HEARTBEAT_SECONDS", "180"))  # 3 min
USER_AGENT = "DxMap/1.0 (far-right-monitoring prototype; worldwide)"

# Worldwide, multilingual. Event/incident-shaped far-right + racist-attack
# terms so the scraper pulls attacks wherever they are reported, not only
# Germany. Override with DXMAP_TERMS (comma-separated) to retune.
SEARCH_TERMS = [t.strip() for t in os.environ.get(
    "DXMAP_TERMS",
    # English / international
    "far-right attack,far right attack,neo-Nazi attack,white supremacist attack,"
    "racist attack,racially motivated attack,xenophobic attack,hate crime attack,"
    "mosque attack,synagogue attack,antisemitic attack,islamophobic attack,"
    "migrant shelter arson,refugee shelter attack,asylum centre arson,"
    "right-wing extremist violence,right-wing terror,neo-Nazi march,"
    # German
    "Neonazi,Rechtsextremismus,Naziaufmarsch,rechte Gewalt,Hakenkreuz,"
    "Volksverhetzung,rechtsextremer Angriff,Brandanschlag Geflüchtete,"
    "Reichsbürger,rassistischer Angriff,Anschlag Moschee,"
    # French
    "attaque raciste,violence d'extrême droite,attaque néonazie,ratonnade,"
    "attaque antisémite,attaque islamophobe,"
    # Spanish / Italian
    "ataque racista,ataque de extrema derecha,attacco razzista,violenza neofascista"
).split(",") if t.strip()]

# German Mastodon instances + far-right-monitoring hashtags (public, no auth).
MASTODON_INSTANCES = [i.strip() for i in os.environ.get(
    "DXMAP_MASTODON_INSTANCES", "mastodon.social,norden.social,nrw.social").split(",") if i.strip()]
MASTODON_TAGS = [t.strip() for t in os.environ.get(
    "DXMAP_MASTODON_TAGS", "Rechtsextremismus,Naziaufmarsch,Nazis,KeinenMeterDenNazis").split(",") if t.strip()]

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "").strip()
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()

# Network geocodes (Nominatim) allowed per heartbeat — keeps us within its
# ~1 req/s policy and bounds beat duration.
GEOCODE_BUDGET = int(os.environ.get("DXMAP_GEOCODE_BUDGET", "6"))

STATE: dict[str, Any] = {
    "started_at": None, "last_beat": None, "beat_count": 0,
    "next_beat_in": HEARTBEAT_SECONDS,
}

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return _TAG_RE.sub("", s or "").strip()


# --------------------------------------------------------------------------- #
# Source adapters -> list of {external_id, title, body, url, category}         #
# --------------------------------------------------------------------------- #

async def _bsky_term(client: httpx.AsyncClient, term: str) -> list[dict[str, Any]]:
    """One Bluesky search query -> normalized items. Failures return []."""
    try:
        resp = await client.get(
            "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts",
            params={"q": term, "limit": 25, "sort": "latest"},
            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except Exception:
        return []
    out = []
    for p in resp.json().get("posts", []):
        uri = p.get("uri", "")
        text = (p.get("record", {}) or {}).get("text", "")
        parts = uri.split("/")
        web = (f"https://bsky.app/profile/{parts[2]}/post/{parts[-1]}"
               if len(parts) >= 5 else "")
        out.append({
            "external_id": f"bsky_{parts[-1]}" if parts else None,
            "title": text[:300] or "(no text)",
            "body": text[:1000], "url": web, "category": term,
        })
    return out


async def source_bluesky(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Search recent Bluesky posts for each event term, in parallel. No key."""
    batches = await asyncio.gather(*[_bsky_term(client, t) for t in SEARCH_TERMS])
    return [item for batch in batches for item in batch]


async def _masto_tag(client: httpx.AsyncClient, inst: str, tag: str) -> list[dict[str, Any]]:
    """One instance+tag timeline -> normalized items. Failures return []."""
    try:
        resp = await client.get(
            f"https://{inst}/api/v1/timelines/tag/{tag}",
            params={"limit": 8}, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except Exception:
        return []  # one instance/tag down shouldn't sink the source
    out = []
    for p in resp.json():
        text = _strip_html(p.get("content", ""))
        out.append({
            "external_id": f"masto_{p.get('id')}",
            "title": text[:300] or "(no text)",
            "body": text[:1000], "url": p.get("url", ""), "category": f"#{tag}",
        })
    return out


async def source_mastodon(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Pull public hashtag timelines across instances, in parallel. No key."""
    jobs = [_masto_tag(client, inst, tag)
            for inst in MASTODON_INSTANCES for tag in MASTODON_TAGS]
    batches = await asyncio.gather(*jobs)
    return [item for batch in batches for item in batch]


async def source_reddit(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Reddit via the free OAuth API. Requires a registered script app."""
    if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        raise RuntimeError("Reddit disabled — set REDDIT_CLIENT_ID/SECRET (free OAuth app)")
    auth = httpx.BasicAuth(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET)
    tok = await client.post("https://www.reddit.com/api/v1/access_token",
                            data={"grant_type": "client_credentials"},
                            auth=auth, headers={"User-Agent": USER_AGENT})
    tok.raise_for_status()
    headers = {"Authorization": f"bearer {tok.json()['access_token']}",
               "User-Agent": USER_AGENT}
    items = []
    for sub in ("news", "worldnews", "weather"):
        r = await client.get(f"https://oauth.reddit.com/r/{sub}/new",
                             params={"limit": 15}, headers=headers)
        r.raise_for_status()
        for child in r.json().get("data", {}).get("children", []):
            d = child.get("data", {})
            items.append({
                "external_id": f"reddit_{d.get('id')}",
                "title": d.get("title", "")[:300],
                "body": (d.get("selftext") or "")[:1000],
                "url": "https://reddit.com" + d.get("permalink", ""),
                "category": sub,
            })
    return items


async def source_youtube(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Recent YouTube uploads matching event terms. Requires a free key."""
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YouTube disabled — set a free YOUTUBE_API_KEY")
    resp = await client.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={"part": "snippet", "type": "video", "order": "date",
                "q": " OR ".join(SEARCH_TERMS[:4]), "maxResults": 15,
                "key": YOUTUBE_API_KEY})
    resp.raise_for_status()
    items = []
    for it in resp.json().get("items", []):
        sn, vid = it.get("snippet", {}), it.get("id", {}).get("videoId")
        items.append({
            "external_id": f"youtube_{vid}",
            "title": sn.get("title", "")[:300],
            "body": (sn.get("description") or "")[:1000],
            "url": f"https://youtube.com/watch?v={vid}", "category": "youtube",
        })
    return items


# --------------------------------------------------------------------------- #
# News + encyclopaedia sources (no key)                                        #
# --------------------------------------------------------------------------- #

WIKIPEDIA_ENABLED = os.environ.get("DXMAP_WIKIPEDIA", "1") != "0"
GDELT_ENABLED = os.environ.get("DXMAP_GDELT", "1") != "0"

# Wikipedia: free-text searches plus category sweeps. Categories are the
# high-signal part — each member is an article about one specific attack,
# usually naming the town and the victim, which classify()/geocode can use.
WIKI_SEARCH = [t.strip() for t in os.environ.get(
    "DXMAP_WIKI_TERMS",
    # worldwide, English
    "racist attack,racially motivated killing,far-right terrorist attack,"
    "white supremacist attack,neo-Nazi murder,hate crime murder,mosque shooting,"
    "synagogue shooting,anti-migrant violence,person of colour killed,"
    # German
    "rassistischer Angriff,rechtsextremer Mord,rassistischer Mordanschlag,"
    "Todesopfer rechtsextremer Gewalt,Brandanschlag Asylbewerberheim,"
    # French / Spanish
    "attaque raciste,crime raciste,ataque racista,violencia de extrema derecha"
).split(",") if t.strip()]
WIKI_CATEGORIES = [c.strip() for c in os.environ.get(
    "DXMAP_WIKI_CATEGORIES",
    "en:Category:Racially motivated violence,"
    "en:Category:Far-right terrorism,"
    "en:Category:Racist murders,"
    "en:Category:Hate crimes,"
    "de:Kategorie:Rassistisch motivierte Gewalt,"
    "de:Kategorie:Rechtsextremes Attentat"
).split(",") if c.strip()]


def _wiki_item(lang: str, title: str, snippet: str) -> dict[str, Any]:
    slug = title.replace(" ", "_")
    return {
        "external_id": f"wiki_{lang}_{slug}"[:120],
        "title": title[:300],
        "body": (_strip_html(snippet) or title)[:1000],
        "url": f"https://{lang}.wikipedia.org/wiki/{slug}",
        "category": "wikipedia",
    }


async def source_wikipedia(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """MediaWiki API — free-text search + category members on de/en Wikipedia."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for term in WIKI_SEARCH:
        lang = "en" if term.isascii() else "de"
        try:
            r = await client.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": term,
                        "srlimit": 15, "srnamespace": 0, "format": "json"},
                headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            for hit in r.json().get("query", {}).get("search", []):
                key = f"{lang}:{hit['title']}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(_wiki_item(lang, hit["title"], hit.get("snippet", "")))
        except Exception:
            continue
    for spec in WIKI_CATEGORIES:
        lang, _, cat = spec.partition(":")
        if not cat:
            continue
        try:
            r = await client.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={"action": "query", "list": "categorymembers", "cmtitle": cat,
                        "cmlimit": 40, "cmtype": "page", "format": "json"},
                headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            for m in r.json().get("query", {}).get("categorymembers", []):
                key = f"{lang}:{m['title']}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(_wiki_item(lang, m["title"], m["title"]))
        except Exception:
            continue
    return out


# GDELT DOC 2.1 — global news index, no key. Rolling recent window per beat;
# the DB accumulates coverage over time. Coordinates come from the downstream
# geocode pass on the headline.
GDELT_QUERIES = [q.strip() for q in os.environ.get(
    "DXMAP_GDELT_QUERIES",
    '"racist attack";"far-right attack";"neo-Nazi attack";"white supremacist attack";'
    '"racially motivated attack";"refugee shelter arson";"person of colour attacked";'
    '"asylum seeker attacked";"mosque attack";"antisemitic attack"'
).split(";") if q.strip()]


async def source_gdelt_news(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Recent world news matching racist/far-right attack queries, Germany-scoped."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in GDELT_QUERIES:
        try:
            r = await client.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={"query": query, "mode": "ArtList", "maxrecords": 50,
                        "timespan": "3d", "format": "json", "sort": "DateDesc"},
                headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            for a in r.json().get("articles", []):
                url = a.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                out.append({
                    "external_id": f"gdelt_{abs(hash(url)) % (10**12)}",
                    "title": (a.get("title") or "")[:300],
                    "body": f"{a.get('domain', '')} · {a.get('seendate', '')}"[:1000],
                    "url": url,
                    "category": "news",
                })
        except Exception:
            continue
    return out


def build_sources() -> list[tuple[str, bool, Optional[Callable]]]:
    """Registry: (name, enabled, adapter). Disabled ones are skipped."""
    return [
        ("bluesky", True, source_bluesky),
        ("mastodon", True, source_mastodon),
        ("wikipedia", WIKIPEDIA_ENABLED, source_wikipedia),
        ("news", GDELT_ENABLED, source_gdelt_news),
        ("reddit", bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET), source_reddit),
        ("youtube", bool(YOUTUBE_API_KEY), source_youtube),
        ("twitter", False, None),    # paid API — see PLAN.md
        ("instagram", False, None),  # no free official API
        ("tiktok", False, None),     # no free official API
    ]


# --------------------------------------------------------------------------- #
# Processing                                                                    #
# --------------------------------------------------------------------------- #

def _store_item(source: str, item: dict[str, Any]) -> Optional[tuple[int, str]]:
    """
    Classify one scraped item, and persist it IF it is far-right-relevant.
    Uses only the instant offline gazetteer for location here; unlocated items
    are returned as (report_id, text) so the caller can geocode off-path.

    Every stored mark carries the four documentation fields:
      reason   = automated signal describing why it was flagged (alleged)
      evidence = the source text + link (the proof)
      law      = a POSSIBLY-applicable statute code (not a verdict)
      impact   = harm/"terror" — left for human review on scraped items
    """
    text = f"{item.get('title', '')} {item.get('body', '')}"
    verdict = lawref.classify(text)
    if not verdict["relevant"]:
        return None  # keep the map focused: skip unrelated posts

    # Gazetteer is Germany-biased (its city list is heaviest there) but not
    # Germany-restricted — a global taxonomy shouldn't silently drop a real
    # geocoded hit just because it falls outside Germany.
    hit = geolocate.from_gazetteer(text)
    lat = lon = place = None
    if hit:
        lat, lon, place = hit

    evidence = item.get("url") or (item.get("title", "")[:280])
    new_id = db.insert_report(
        source=source, external_id=item.get("external_id"),
        title=item.get("title", "(untitled)"), body=item.get("body"),
        url=item.get("url"), category=verdict["category"],
        reason=verdict["reason"],
        evidence=evidence,
        law=verdict["law_code"],
        impact=None,                     # scraped: unknown until reviewed
        # status: left to insert_report's default — 'unverified' since a
        # scraped item always carries a real source `url` as evidence.
        lat=lat, lon=lon, place=place)
    if new_id is not None and hit is None:
        return new_id, text              # newly stored, awaiting geocode
    return None


async def run_one_source(name: str, adapter: Callable,
                        client: httpx.AsyncClient) -> list[tuple[int, str]]:
    """
    Poll a single source and persist results with gazetteer-only geolocation.
    Heartbeat latency measures the SCRAPE only (source responsiveness), not the
    downstream geocoding. Returns the list of unlocated (id, text) to geocode.
    """
    t0 = time.time()
    try:
        raw = await adapter(client)
        fetch_ms = int((time.time() - t0) * 1000)
        pending = [pr for it in raw if (pr := _store_item(name, it))]
        db.record_heartbeat(source=name, ok=True, found=len(raw),
                            latency_ms=fetch_ms,
                            detail=f"fetched={len(raw)} pending_geocode={len(pending)}")
        return pending
    except Exception as exc:  # isolate: one bad source must not stop others
        db.record_heartbeat(source=name, ok=False,
                            latency_ms=int((time.time() - t0) * 1000),
                            detail=str(exc)[:200])
        return []


def _geocode_pending(pending: list[tuple[int, str]], budget: int) -> int:
    """
    Blocking geocode pass (runs in a worker thread). Resolves up to `budget`
    unlocated reports via Nominatim and updates them. Returns count resolved.
    """
    resolved = 0
    for report_id, text in pending:
        if resolved >= budget:
            break
        hit = geolocate.from_nominatim(" ".join(text.split()[:8]))
        if hit:
            db.set_location(report_id, *hit)
            resolved += 1
    return resolved


async def heartbeat_once() -> None:
    """
    One beat: scrape all enabled sources in parallel (fast), then geocode the
    unlocated items in a worker thread so the event loop is never blocked.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        tasks = [run_one_source(n, a, client)
                 for (n, en, a) in build_sources() if en and a]
        results = await asyncio.gather(*tasks) if tasks else []
    pending = [pr for sub in results for pr in sub]
    if pending:
        # Off the critical path; won't block other requests or the loop.
        await asyncio.to_thread(_geocode_pending, pending, GEOCODE_BUDGET)
    STATE["last_beat"] = int(time.time())
    STATE["beat_count"] += 1


async def heartbeat_loop() -> None:
    """The persistent heartbeat; never dies (per-source failures are isolated)."""
    STATE["started_at"] = int(time.time())
    while True:
        try:
            await heartbeat_once()
        except Exception:
            pass
        for remaining in range(HEARTBEAT_SECONDS, 0, -1):
            STATE["next_beat_in"] = remaining
            await asyncio.sleep(1)


if __name__ == "__main__":
    db.init_db()
    asyncio.run(heartbeat_once())
    print("Heartbeat complete:", db.stats())
