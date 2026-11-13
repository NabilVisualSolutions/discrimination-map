"""RSS/Atom incident feeds: parsing, the incident filter, polite fetching and
what ends up in the database. No network: every request goes to a mock transport."""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)
os.environ["DXMAP_AGENT"] = "off"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import httpx  # noqa: E402
import pytest  # noqa: E402

import agent  # noqa: E402
import db  # noqa: E402
import rssfeeds  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
NOW = int(time.mktime((2026, 10, 21, 12, 0, 0, 0, 0, 0)))
db.init_db()


@pytest.fixture(autouse=True)
def _clean_state():
    rssfeeds.reset_state()
    yield
    rssfeeds.reset_state()


def read(name):
    return (FIX / name).read_bytes()


# ---- parsing ----------------------------------------------------------------

def test_parse_rss2_atom_and_rdf():
    rss = rssfeeds.parse_feed(read("sample.rss"))
    assert rss["ttl_minutes"] == 60 and len(rss["items"]) == 5
    assert rss["items"][0]["title"].startswith("Mosque set on fire")
    assert "<" not in rss["items"][0]["summary"]
    atom = rssfeeds.parse_feed(read("sample.atom"))
    assert atom["items"][0]["link"] == "https://chronik.example.org/eintrag/42"   # rel=alternate, not self
    assert atom["items"][0]["date"] is not None
    rdf = rssfeeds.parse_feed(read("sample.rdf"))
    assert rdf["items"][0]["link"] == "https://r.example.org/1" and rdf["items"][0]["date"]


def test_parse_rejects_html_garbage_and_entity_bombs():
    with pytest.raises(ValueError):
        rssfeeds.parse_feed(b"<html><body>Not a feed</body></html>")
    with pytest.raises(ValueError):
        rssfeeds.parse_feed(b"not xml at all")
    with pytest.raises(ValueError):
        rssfeeds.parse_feed(read("evil.xml"))
    with pytest.raises(ValueError):
        rssfeeds.parse_feed(b"<rss>" + b"x" * (rssfeeds.MAX_BYTES + 1))


# ---- snippet, urls, titles --------------------------------------------------

def test_snippet_is_at_most_160_chars_and_cut_at_a_word():
    text = ("word " * 80).strip()
    s = rssfeeds.make_snippet(text)
    assert len(s) <= 160 and s.endswith("…")
    assert s[:-1].split(" ")[-1] == "word"              # no half word before the ellipsis
    assert rssfeeds.make_snippet("short text") == "short text"
    long_word = "x" * 400
    assert len(rssfeeds.make_snippet(long_word)) <= 160
    assert len(rssfeeds.make_snippet("<p>" + "ab " * 200 + "</p>")) <= 160


def test_url_and_title_normalisation():
    a = rssfeeds.normalize_url("https://n.example.org/a/x/?utm_source=rss&id=7&fbclid=zz#frag")
    assert a == "https://n.example.org/a/x?id=7"
    assert rssfeeds.normalize_title("Mosque set ON fire in Leeds! - The Guardian") == \
        rssfeeds.normalize_title("mosque set on fire in leeds | BBC News")


# ---- the incident filter -----------------------------------------------------

REAL = [
    "Mosque set on fire in Leeds, police investigate",
    "Man in court after three Jewish women assaulted",
    "Police probe racist graffiti on school wall in Bristol",
    "Neo-Nazi rally held in Dresden",
    "Brandanschlag auf Flüchtlingsunterkunft in Zwickau: Polizei ermittelt",
    "Synagoge in Halle mit Hakenkreuzen beschmiert",
    "Agression raciste à Lyon : un homme frappé, la police enquête",
    "Ataque racista contra un joven en Madrid: la policía detiene a dos hombres",
    "Aggressione razzista a Roma: un ragazzo picchiato, indagano i carabinieri",
    "Man jailed over death threats to two Manchester mosques",
]
NOT_REAL = [
    "Opinion: Why racism still shapes how we police our cities",
    "Government must act against racist attacks, says charity",
    "Annual report: hate crime figures rise across Europe",
    "Join our webinar on antisemitism in schools",
    "Donate now to support victims of racist violence",
    "Jahresbericht 2025: Zahlen rechter Gewalt veröffentlicht",
    "Veranstaltung: Lesung gegen Rassismus in Dresden",
    "Trump attacks migrants and communists as he tries to exploit unrest",
    "Italy to deploy 500 troops to Milan after days of protests and looting",
    "FRA contributes to Forum on combating antisemitism",
    "How to talk to your children about racism?",
    "Rebellion review – story of Bradford 12 revisits Britain's ugly racist past",
    "Caminhão-tanque com piche pega fogo no litoral de SP",
    "Meinung: Rassismus beginnt im Alltag",
]


@pytest.mark.parametrize("title", REAL)
def test_filter_keeps_specific_incidents(title):
    assert rssfeeds.looks_like_incident(title, "")


@pytest.mark.parametrize("title", NOT_REAL)
def test_filter_drops_opinion_policy_events_and_noise(title):
    assert not rssfeeds.looks_like_incident(title, "A mosque, racism, an attack, police and a man.")


def test_filter_url_path_veto_and_chronicle_mode():
    assert not rssfeeds.looks_like_incident("Mosque set on fire in Leeds, police investigate", "",
                                            "https://x.example.org/opinion/mosque-fire")
    # a chronicle that lists only incidents needs no hate-context word...
    assert rssfeeds.looks_like_incident("Mann am Bahnhof angegriffen und beleidigt, Polizei ermittelt", "", mode="chronicle")
    # ...a news feed does
    assert not rssfeeds.looks_like_incident("Mann am Bahnhof angegriffen, Polizei ermittelt", "", mode="news")


# ---- feed_items: what leaves the module ------------------------------------

FEED = {"url": "https://news.example.org/feed", "publisher": "Example News", "mode": "news"}


def test_feed_items_keeps_only_recent_real_incidents_with_short_snippets():
    parsed = rssfeeds.parse_feed(read("sample.rss"))
    items = rssfeeds.feed_items(FEED, parsed, now=NOW)
    titles = [i["title"] for i in items]
    assert titles == ["Mosque set on fire in Leeds, police investigate",
                      "Brandanschlag auf Flüchtlingsunterkunft in Zwickau: Polizei ermittelt"]
    first = items[0]
    assert first["url"] == "https://news.example.org/a/mosque-fire"        # tracking params gone
    assert first["source_name"] == "Example News"
    assert len(first["body"]) <= 160 and "<" not in first["body"]
    assert first["occurred_at"] == rssfeeds.parse_date("Tue, 20 Oct 2026 09:30:00 GMT")
    assert set(first) == {"external_id", "title", "body", "url", "category", "source_name",
                          "occurred_at", "prefilter", "_dedupe_title"}      # nothing else leaves
    assert first["prefilter"]["category"] == "islamophobia"


def test_feed_items_caps_items_per_feed(monkeypatch):
    monkeypatch.setattr(rssfeeds, "MAX_ITEMS_PER_FEED", 1)
    assert len(rssfeeds.feed_items(FEED, rssfeeds.parse_feed(read("sample.rss")), now=NOW)) == 1


def test_atom_chronicle_entry_passes_and_report_is_dropped():
    parsed = rssfeeds.parse_feed(read("sample.atom"))
    items = rssfeeds.feed_items({**FEED, "mode": "chronicle"}, parsed, now=NOW)
    assert [i["title"] for i in items] == ["Synagoge in Halle mit Hakenkreuzen beschmiert"]


# ---- polite fetching --------------------------------------------------------

def make_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)


def run(coro):
    return asyncio.run(coro)


def test_conditional_get_user_agent_robots_and_ttl():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.url.path, dict(req.headers)))
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=read("sample.rss"),
                              headers={"ETag": '"v1"', "Last-Modified": "Tue, 20 Oct 2026 10:00:00 GMT"})

    async def go():
        async with make_client(handler) as c:
            first = await rssfeeds.fetch_feed(c, FEED, now=1000.0)
            soon = await rssfeeds.fetch_feed(c, FEED, now=1100.0)          # not due: no request at all
            later = await rssfeeds.fetch_feed(c, FEED, now=1000.0 + 4000)  # due: conditional GET -> 304
            return first, soon, later

    first, soon, later = run(go())
    assert first and len(first["items"]) == 5
    assert soon is None and later is None
    feed_calls = [h for p, h in calls if p == "/feed"]
    assert len(feed_calls) == 2                                   # the "soon" call made none
    assert feed_calls[0]["user-agent"].startswith("dxmap-agent (+https://map.nabilvs.com)")
    assert feed_calls[1]["if-none-match"] == '"v1"'
    assert "if-modified-since" in feed_calls[1]
    assert rssfeeds._STATE[FEED["url"]]["ttl"] == 60              # the feed's own <ttl>
    assert sum(1 for p, _ in calls if p == "/robots.txt") == 1    # robots cached per host


def test_robots_disallow_means_no_feed_request():
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /feed\n")
        return httpx.Response(200, content=read("sample.rss"))

    async def go():
        async with make_client(handler) as c:
            return await rssfeeds.fetch_feed(c, FEED, now=1000.0)

    assert run(go()) is None and seen == ["/robots.txt"]


def test_backoff_on_errors_and_retry_after():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(429, headers={"Retry-After": "1800"})

    async def go():
        async with make_client(handler) as c:
            r1 = await rssfeeds.fetch_feed(c, FEED, now=1000.0)
            r2 = await rssfeeds.fetch_feed(c, FEED, now=1000.0 + 600)       # still backing off
            return r1, r2

    r1, r2 = run(go())
    assert r1 is None and r2 is None
    st = rssfeeds._STATE[FEED["url"]]
    assert st["fails"] == 1 and st["next_at"] >= 1000.0 + 1800 - 1

    def handler500(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(500)

    async def two():
        async with make_client(handler500) as c:
            await rssfeeds.fetch_feed(c, FEED, now=1000.0)
            d1 = rssfeeds._STATE[FEED["url"]]["next_at"] - 1000.0
            t2 = rssfeeds._STATE[FEED["url"]]["next_at"] + 1
            await rssfeeds.fetch_feed(c, FEED, now=t2)
            return d1, rssfeeds._STATE[FEED["url"]]["next_at"] - t2

    rssfeeds.reset_state()
    d1, d2 = run(two())
    assert (d1, d2) == (300, 600)                       # doubles after each failure


def test_garbage_response_is_a_failure_not_a_crash():
    def handler(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text="<html>nope</html>")

    async def go():
        async with make_client(handler) as c:
            return await rssfeeds.fetch_feed(c, FEED, now=1000.0)

    assert run(go()) is None
    assert rssfeeds._STATE[FEED["url"]]["fails"] == 1


# ---- end to end through the agent -------------------------------------------

def test_source_rss_stores_unverified_with_attribution_and_dedupes(monkeypatch, tmp_path):
    feeds_file = tmp_path / "feeds.json"
    feeds_file.write_text(json.dumps({"feeds": [
        {"url": "https://news.example.org/feed", "publisher": "Example News", "mode": "news", "enabled": True},
        {"url": "https://off.example.org/feed", "publisher": "Off", "enabled": False},
    ]}))
    monkeypatch.setattr(rssfeeds, "FEEDS_FILE", str(feeds_file))
    monkeypatch.setattr(rssfeeds, "MAX_AGE_DAYS", 100000)         # fixture dates are fixed

    # One of the two incidents is already on the map under a different URL: same headline.
    db.insert_report(source="bluesky", external_id="pre1", title="Mosque set on fire in Leeds, police investigate - BBC",
                     url="https://bsky.example/post/1", status="unverified",
                     created_at=rssfeeds.parse_date("Tue, 20 Oct 2026 12:00:00 GMT"))

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        assert req.url.host == "news.example.org"                 # the disabled feed is never contacted
        return httpx.Response(200, content=read("sample.rss"))

    async def go():
        async with make_client(handler) as c:
            return await agent.run_one_source("rss", agent.source_rss, c)

    run(go())
    with db._conn() as conn:
        rows = conn.execute("SELECT * FROM reports WHERE source = 'rss'").fetchall()
    assert [r["title"] for r in rows if "Zwickau" in r["title"]]               # the new one is stored
    assert not [r for r in rows if "Leeds" in r["title"]]                      # title duplicate skipped
    for r in rows:
        assert r["status"] == "unverified" and r["verified"] == 0 and r["human_verified"] == 0
        assert r["url"].startswith("https://news.example.org/")
        assert r["source_name"] == "Example News"
        assert len(r["body"] or "") <= 160
        assert r["human_verified_at"] is None
    z = [r for r in rows if "Zwickau" in r["title"]][0]
    assert z["located"] == 1 and "Zwickau" in z["place"]                       # offline gazetteer
    assert z["occurred_at"] == rssfeeds.parse_date("Mon, 19 Oct 2026 07:00:00 +0200")

    # Second run: same feed, nothing new (URL dedupe against the rows we just wrote).
    rssfeeds.reset_state()
    run(go())
    with db._conn() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM reports WHERE source = 'rss'").fetchone()["n"] == len(rows)


def test_item_without_a_place_stays_unlocated(monkeypatch, tmp_path):
    xml = ("<rss version='2.0'><channel><item><title>Racist graffiti found on a school wall, police say</title>"
           "<link>https://noplace.example.org/1</link><pubDate>Tue, 20 Oct 2026 09:30:00 GMT</pubDate>"
           "<description>Pupils were shocked.</description></item></channel></rss>").encode()
    ff = tmp_path / "f.json"
    ff.write_text(json.dumps({"feeds": [{"url": "https://noplace.example.org/feed", "publisher": "NP"}]}))
    monkeypatch.setattr(rssfeeds, "FEEDS_FILE", str(ff))
    monkeypatch.setattr(rssfeeds, "MAX_AGE_DAYS", 100000)

    def handler(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, content=xml)

    async def go():
        async with make_client(handler) as c:
            return await agent.run_one_source("rss", agent.source_rss, c)

    pending = run(go())
    with db._conn() as conn:
        r = conn.execute("SELECT * FROM reports WHERE url = 'https://noplace.example.org/1'").fetchone()
    assert r is not None and r["located"] == 0 and r["lat"] is None and r["status"] == "unverified"
    assert pending and pending[0][0] == r["id"]          # queued for the rate-limited online geocoder


# ---- the shipped feed list ---------------------------------------------------

def test_shipped_feed_list_is_well_formed():
    data = json.loads((Path(__file__).parent.parent / "backend" / "feeds.json").read_text())
    feeds = data["feeds"]
    assert 20 <= len(feeds) <= 40
    urls = [f["url"] for f in feeds]
    assert len(set(urls)) == len(urls) and all(u.startswith("https://") for u in urls)
    assert all(f.get("publisher") and f.get("region") and f.get("lang") for f in feeds)
    doc = (Path(__file__).parent.parent / "docs" / "FEEDS.md").read_text()
    assert all(u in doc for u in urls)                    # every shipped feed is documented


def test_env_url_override(monkeypatch):
    monkeypatch.setenv("DXMAP_RSS_URLS", "https://a.example/feed, https://b.example/rss")
    assert [f["url"] for f in rssfeeds.load_feeds()] == ["https://a.example/feed", "https://b.example/rss"]


# ---- hostile input -------------------------------------------------------------

BOMB = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><rss version="2.0"><channel><item><title>&b;</title>'
        '<link>https://x.example/1</link></item></channel></rss>')


@pytest.mark.parametrize("data", [
    BOMB.encode("utf-16"),                                   # BOM + NUL-interleaved
    BOMB.encode("utf-16-le"),                                # no BOM, NULs only
    BOMB.encode("utf-16-be"),
    BOMB.replace("UTF-16", "UTF-32").encode("utf-32"),
    b"<?xml version='1.0' encoding='utf-16'?><rss version='2.0'><channel/></rss>",   # declared, harmless body
    b"<?xml version='1.0'?><!DOCTYPE rss [ ]><rss version='2.0'><channel/></rss>",   # DOCTYPE without entities
    b"<?xml version='1.0'?><!doctype rss SYSTEM 'http://169.254.169.254/x.dtd'><rss version='2.0'/>",
    b"<?xml version='1.0'?><!  DOCTYPE rss><rss version='2.0'/>",
])
def test_doctype_and_utf16_documents_are_refused(data):
    with pytest.raises(ValueError):
        rssfeeds.parse_feed(data)


def test_title_is_cut_before_the_incident_regexes_run():
    huge = "x" * 5_000_000 + " mosque set on fire"
    parsed = rssfeeds.parse_feed(("<rss version='2.0'><channel><item><title>%s</title><link>https://a.example/1</link>"
                                  "</item></channel></rss>" % huge[:1_900_000]).encode())
    assert len(parsed["items"][0]["title"]) <= rssfeeds.TITLE_MAX
    t = time.time()
    assert rssfeeds.looks_like_incident("a" * 3_000_000, "b" * 3_000_000) is False
    assert time.time() - t < 1.0


@pytest.mark.parametrize("target", ["http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data/",
                                    "https://localhost/feed"])
def test_redirects_are_never_followed_for_feed_or_robots(target):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if req.url.host == "evil.example":
            return httpx.Response(302, headers={"Location": target})
        return httpx.Response(200, text="should never be fetched")

    feed = {"url": "https://evil.example/feed", "publisher": "E"}

    async def go():
        async with make_client(handler) as c:
            return await rssfeeds.fetch_feed(c, feed, now=1000.0)

    assert run(go()) is None
    assert all("evil.example" in u for u in seen)            # nothing was requested at the Location
    assert seen == ["https://evil.example/robots.txt"]       # a redirecting robots.txt ends the attempt
    assert rssfeeds._STATE[feed["url"]]["fails"] == 1


def test_feed_redirect_is_refused_even_when_robots_is_fine():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(301, headers={"Location": "http://169.254.169.254/"})

    async def go():
        async with make_client(handler) as c:
            return await rssfeeds.fetch_feed(c, FEED, now=1000.0)

    assert run(go()) is None
    assert seen == ["https://news.example.org/robots.txt", "https://news.example.org/feed"]


@pytest.mark.parametrize("url", ["http://127.0.0.1/feed", "https://10.0.0.5/feed", "https://169.254.169.254/f",
                                 "https://[::1]/feed", "ftp://x.example/feed", "https://localhost/feed"])
def test_private_and_odd_urls_are_not_requested(url):
    seen = []

    async def go():
        async with make_client(lambda r: seen.append(str(r.url)) or httpx.Response(200)) as c:
            return await rssfeeds.fetch_feed(c, {"url": url, "publisher": "X"}, now=1000.0)

    assert run(go()) is None and seen == []


def test_huge_feed_and_huge_robots_are_cut_off_while_streaming(monkeypatch):
    chunks = []

    class Endless(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(5000):
                chunks.append(1)
                yield b"y" * 100_000

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, stream=Endless())
        return httpx.Response(200, stream=Endless())

    async def go():
        async with make_client(handler) as c:
            return await rssfeeds.fetch_feed(c, FEED, now=1000.0)

    assert run(go()) is None
    assert len(chunks) <= 4                                  # robots.txt stopped at 256 KB, never reached the feed

    rssfeeds.reset_state()
    chunks.clear()

    def handler2(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, stream=Endless())

    async def go2():
        async with make_client(handler2) as c:
            return await rssfeeds.fetch_feed(c, FEED, now=1000.0)

    assert run(go2()) is None
    assert len(chunks) <= 22                                 # 2 MB cap, not 500 MB


def test_slow_body_hits_the_wall_clock_deadline(monkeypatch):
    monkeypatch.setattr(rssfeeds, "FEED_DEADLINE_S", 0.2)

    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(0.1)
                yield b"<"

    def handler(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, stream=Trickle())

    async def go():
        async with make_client(handler) as c:
            t = time.time()
            r = await rssfeeds.fetch_feed(c, FEED, now=1000.0)
            return r, time.time() - t

    r, took = run(go())
    assert r is None and took < 1.0
    assert rssfeeds._STATE[FEED["url"]]["fails"] == 1


def test_shipped_feeds_need_no_redirect_hint():
    # The feed list holds final URLs: none of them may be one of the six that used to redirect.
    urls = [f["url"] for f in json.loads((Path(__file__).parent.parent / "backend" / "feeds.json").read_text())["feeds"]]
    for old in ["https://www.verband-brg.de/feed/", "https://www.tellmamauk.org/feed/",
                "https://www.searchlightmagazine.com/feed/", "https://www.svt.se/nyheter/rss.xml",
                "https://www.bbc.com/mundo/index.xml", "https://www.ilga-europe.org/feed"]:
        assert old not in urls


# ---- de-duplication ----------------------------------------------------------------

T0 = rssfeeds.parse_date("Tue, 20 Oct 2026 09:30:00 GMT")


def rows(*r):
    return [dict(url=u, title=t, status=st, place=pl, ts=ts) for u, t, st, pl, ts in r]


def test_same_url_always_counts_whatever_its_status():
    d = rssfeeds.Deduper(rows(("https://a.example/x?utm_source=q", "Old", "dismissed", None, T0 - 99 * 86400)))
    assert d.seen("https://a.example/x", "other title", T0, None)


def test_same_headline_in_a_different_week_or_town_is_a_new_incident():
    key = rssfeeds.normalize_title("Mosque attacked")
    d = rssfeeds.Deduper(rows(("https://a.example/1", "Mosque attacked", "unverified", "Leeds, UK", T0)))
    assert d.seen("https://b.example/2", key, T0 + 3600, "Leeds, UK")                 # same place, same day: duplicate
    assert d.seen("https://b.example/2", key, T0 + 3600, None)                         # place unknown on one side: duplicate
    assert not d.seen("https://b.example/2", key, T0 + 3600, "Manchester, UK")         # another town
    assert not d.seen("https://b.example/2", key, T0 + 4 * 86400, "Leeds, UK")         # outside 3 days
    assert d.seen("https://b.example/2", key, T0 + 2 * 86400, "Leeds, UK")


def test_a_dismissed_lead_does_not_block_the_headline_forever():
    key = rssfeeds.normalize_title("Mosque attacked")
    d = rssfeeds.Deduper(rows(("https://a.example/1", "Mosque attacked", "dismissed", "Leeds, UK", T0),
                              ("https://a.example/2", "Mosque attacked", "irrelevant", None, T0)))
    assert not d.seen("https://b.example/9", key, T0 + 60, "Leeds, UK")


def test_items_added_in_this_run_dedupe_later_ones():
    key = rssfeeds.normalize_title("Mosque attacked in Leeds")
    d = rssfeeds.Deduper([])
    assert not d.seen("https://a.example/1", key, T0, "Leeds, UK")
    d.add("https://a.example/1", key, T0, "Leeds, UK")
    assert d.seen("https://c.example/other", key, T0 + 100, "Leeds, UK")


def test_source_rss_keeps_a_same_titled_incident_in_another_town(monkeypatch, tmp_path):
    def feed(host, title, link, date):
        return (f"<rss version='2.0'><channel><item><title>{title}</title><link>{link}</link><pubDate>{date}</pubDate>"
                "<description>Police are investigating.</description></item></channel></rss>").encode()
    ff = tmp_path / "f.json"
    ff.write_text(json.dumps({"feeds": [{"url": "https://dd.example/feed", "publisher": "DD"}]}))
    monkeypatch.setattr(rssfeeds, "FEEDS_FILE", str(ff))
    monkeypatch.setattr(rssfeeds, "MAX_AGE_DAYS", 100000)
    db.insert_report(source="bluesky", external_id="dd0", title="Racist graffiti on mosque in Leeds, police say",
                     url="https://bsky.example/dd0", status="dismissed",
                     created_at=rssfeeds.parse_date("Tue, 20 Oct 2026 09:00:00 GMT"))
    xml = feed("dd", "Racist graffiti on mosque in Leeds, police say", "https://dd.example/leeds", "Tue, 20 Oct 2026 10:00:00 GMT")

    def handler(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, content=xml)

    async def go():
        async with make_client(handler) as c:
            return await agent.run_one_source("rss", agent.source_rss, c)

    run(go())
    with db._conn() as c:
        assert c.execute("SELECT COUNT(*) n FROM reports WHERE url='https://dd.example/leeds'").fetchone()["n"] == 1
