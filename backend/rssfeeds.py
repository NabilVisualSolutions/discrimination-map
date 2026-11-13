"""
Open RSS/Atom incident feeds -> candidate reports.

What this module stores per item, and nothing more: the headline, the link to
the original, the publisher's name, the publication date and a SHORT snippet
(at most 160 characters, cut at a word boundary). Never article text, never
images. Every item enters the map as 'unverified' with its real source URL.

Good-citizen rules, all enforced here:
  * identifying User-Agent, request timeout, response size cap
  * robots.txt is read per host (cached 24 h) and obeyed
  * conditional GET (ETag / Last-Modified); a 304 costs almost nothing
  * the feed's own <ttl> (and a floor of DXMAP_RSS_MIN_INTERVAL) bounds how
    often it is fetched; Retry-After is honoured
  * exponential backoff per feed after any error
  * at most DXMAP_RSS_MAX_ITEMS items taken per feed per fetch

The feed list lives in backend/feeds.json (edit it without touching code);
DXMAP_RSS_FEEDS points at another file, DXMAP_RSS_URLS="url1,url2" replaces
the list with bare URLs.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

import geolocate

RSS_USER_AGENT = os.environ.get("DXMAP_RSS_UA", "dxmap-agent (+https://map.nabilvs.com)")
FEEDS_FILE = os.environ.get("DXMAP_RSS_FEEDS", str(Path(__file__).with_name("feeds.json")))
MAX_ITEMS_PER_FEED = int(os.environ.get("DXMAP_RSS_MAX_ITEMS", "20"))
MIN_INTERVAL = int(os.environ.get("DXMAP_RSS_MIN_INTERVAL", "900"))        # seconds between fetches of one feed
MAX_AGE_DAYS = int(os.environ.get("DXMAP_RSS_MAX_AGE_DAYS", "7"))
MAX_BYTES = 2_000_000
ROBOTS_MAX_BYTES = 256 * 1024
FEED_DEADLINE_S = float(os.environ.get("DXMAP_RSS_DEADLINE", "30"))   # wall clock per feed, robots.txt included
TITLE_MAX = 300
SUMMARY_MAX = 2000
log = logging.getLogger("dxmap.rss")
SNIPPET_MAX = 160
MAX_BACKOFF = 6 * 3600
ROBOTS_TTL = 24 * 3600

# --------------------------------------------------------------------------- #
# Text helpers                                                                 #
# --------------------------------------------------------------------------- #

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(s: Optional[str]) -> str:
    """Markup and entities out, whitespace collapsed."""
    if not s:
        return ""
    s = re.sub(r"<!\[CDATA\[|\]\]>", "", s)
    s = _TAG_RE.sub(" ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
         .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'").replace("&#8217;", "’"))
    return _WS_RE.sub(" ", s).strip()


def make_snippet(text: str, limit: int = SNIPPET_MAX) -> str:
    """At most `limit` characters INCLUDING the ellipsis, cut at a word boundary."""
    text = clean_text(text)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    # Cut on the last whitespace so no word is chopped in half.
    if not text[limit - 1].isspace():
        sp = cut.rfind(" ")
        cut = cut[:sp] if sp > 0 else cut
    return cut.rstrip(" ,;:.-–—") + "…"


_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|ref_|cmp$|at_|xtor$|igshid$|wt_)", re.I)


def normalize_url(url: str) -> str:
    """Drop tracking parameters and fragments, so one article is one URL."""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip()
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/") if len(p.path) > 1 else p.path,
                       p.params, urlencode(q), "")).rstrip("/")


def normalize_title(title: str) -> str:
    """For duplicate detection: case, accents, punctuation, a trailing
    ' - Publisher' / ' | Publisher' tag and whitespace do not matter."""
    t = clean_text(title)
    t = re.split(r"\s[|–—-]\s(?=[^|–—-]{2,40}$)", t)[0]
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", t).strip()


# --------------------------------------------------------------------------- #
# Parsing RSS 2.0 / RSS 1.0 (RDF) / Atom                                       #
# --------------------------------------------------------------------------- #

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(el: ET.Element, *names: str) -> str:
    for ch in el:
        if _local(ch.tag) in names and (ch.text or "").strip():
            return ch.text.strip()
    return ""


def parse_date(s: str) -> Optional[int]:
    if not s:
        return None
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def parse_feed(data: bytes) -> dict[str, Any]:
    """-> {"ttl_minutes": int|None, "items": [{title, link, date, summary, guid}]}.
    Raises ValueError for anything that is not a valid RSS/Atom document."""
    if len(data) > MAX_BYTES:
        raise ValueError("feed too large")
    # Feeds never need a DOCTYPE, and a DOCTYPE is where entity bombs live.
    # UTF-16/32 documents are refused outright: they hide the DOCTYPE from a
    # byte search and no real feed we use is encoded that way.
    head = data[:400]
    if (data.startswith((b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")) or b"\x00" in head
            or re.search(rb"encoding\s*=\s*[\"'](?:utf-?(?:16|32)|ucs-?[24])", head, re.I)):
        raise ValueError("UTF-16/32 documents are not accepted")
    if re.search(rb"<!\s*(?:doctype|entity)", data, re.I):
        raise ValueError("DOCTYPE / entity declarations are not accepted")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"not XML: {exc}") from exc
    kind = _local(root.tag)
    if kind not in ("rss", "rdf", "feed"):
        raise ValueError(f"not an RSS/Atom feed (root <{kind}>)")
    ttl = None
    items: list[dict[str, Any]] = []
    for el in root.iter():
        name = _local(el.tag)
        if name == "ttl" and ttl is None and (el.text or "").strip().isdigit():
            ttl = int(el.text.strip())
        if name not in ("item", "entry"):
            continue
        link = ""
        if name == "entry":
            for ch in el:
                if _local(ch.tag) == "link":
                    rel = ch.attrib.get("rel", "alternate")
                    if rel == "alternate" and ch.attrib.get("href"):
                        link = ch.attrib["href"]
                        break
            if not link:
                for ch in el:
                    if _local(ch.tag) == "link" and ch.attrib.get("href"):
                        link = ch.attrib["href"]
                        break
        else:
            link = _child_text(el, "link")
            if not link:
                guid = _child_text(el, "guid")
                link = guid if guid.startswith("http") else ""
        date = parse_date(_child_text(el, "pubdate", "published", "updated", "date", "issued"))
        items.append({
            "title": clean_text(_child_text(el, "title")[:TITLE_MAX * 4])[:TITLE_MAX],
            "link": link.strip(),
            "date": date,
            "summary": clean_text(_child_text(el, "description", "summary", "content", "encoded")[:SUMMARY_MAX * 4])[:SUMMARY_MAX],
            "guid": _child_text(el, "guid", "id"),
        })
    return {"ttl_minutes": ttl, "items": items}


# --------------------------------------------------------------------------- #
# Real-incident filter                                                         #
# --------------------------------------------------------------------------- #
# Keep reports of a specific incident (attack, arson, assault, harassment,
# desecration, rally, banned symbol, discrimination case). Drop opinion,
# analysis, policy statements, fundraising and event listings.

def _rx(words: str) -> re.Pattern:
    return re.compile(words, re.IGNORECASE)


# A violent, vandal or abusive act, as a headline states it. These are the
# words an incident report has in its TITLE. Short words carry \b on both sides:
# a loose prefix such as "cami" matched "caminhão" in a first draft.
_ACT = _rx("|".join([
    # en
    r"\battacked\b", r"\battacks? (?:on|against)\b", r"\b(?:racist|racial|terror|knife|arson|violent|far-right|neo-nazi|antisemitic|islamophobic|xenophobic|homophobic|transphobic) attacks?\b",
    r"\bassault(?:ed)?\b", r"\barson\b", r"\btorch(?:ed)?\b", r"\bset (?:on )?fire\b", r"\bfire-?bomb\w*",
    r"\bstabb(?:ed|ing)\b", r"\bbeaten\b", r"\bbeat(?:ing)? up\b", r"\bkilled\b", r"\bmurder(?:ed)?\b", r"\bshot dead\b",
    r"\bshooting\b", r"\bvandal(?:ised|ized|ism)\b", r"\bdesecrat\w+", r"\bdefaced?\b", r"\bgraffiti\b", r"\bswastikas?\b",
    r"\bharass(?:ed|ment)\b", r"\bracially (?:abused|aggravated)\b", r"\brac(?:ial|ist) abuse\b", r"\bspat (?:at|on)\b",
    r"\bthreat(?:ened|s)\b", r"\bdeath threats?\b", r"\bhate crimes?\b", r"\bnoose\b", r"\bburn(?:ed|t) down\b",
    r"\blynch\w*", r"\bpogrom\b", r"\bdenied (?:entry|service)\b", r"\bturned away\b", r"\babused\b", r"\battacker\b",
    # de
    r"\bangriff\b", r"\bangegriffen\b", r"\bbrandanschlag\b", r"\banschlag\b", r"\büberfall\w*", r"\bzusammengeschlagen\b",
    r"\bgeschlagen\b", r"\bbeleidigt\b", r"\bbedroht\b", r"\bschändung\b", r"\bgeschändet\b", r"\bhakenkreuz\w*",
    r"\bschmier\w*", r"\bbrandstiftung\b", r"\bangezündet\b", r"\bvolksverhetzung\b", r"\bhitlergru\w*",
    r"\bniedergestochen\b", r"\bgewalttat\w*", r"\bübergriff\w*", r"\bdrohungen?\b", r"\bangegangen\b", r"\bbepöbelt\b",
    # fr
    r"\bagress\w+", r"\battaque\w*", r"\bincendi\w+", r"\bprofanation\b", r"\bprofané\w*", r"\btags?\b", r"\bsaccag\w+",
    r"\bmenaces?\b", r"\binsultes? racistes?\b", r"\bcroix gammée\w*", r"\bpassage à tabac\b", r"\bpoignardé\w*",
    # es / pt / it
    r"\bagresi[oó]n\b", r"\bataque\w*", r"\bprofanaci[oó]n\b", r"\bpintadas?\b", r"\bamenazas?\b", r"\bapuñalad\w+",
    r"\bagress[aã]o\b", r"\bincêndio criminoso\b", r"\bpichação\b", r"\bpichações\b", r"\binj[uú]ria racial\b", r"\bapunhalad\w+",
    r"\baggressione\b", r"\baggredit[oa]\b", r"\bprofanazione\b", r"\bscritte\b", r"\bminacce\b", r"\bsvastiche?\b", r"\baccoltellat\w+",
    # nl / nordic
    r"\baanval\b", r"\bmishandeld\b", r"\bbrandstichting\b", r"\bvernield\b", r"\bövergrepp\b", r"\bangrep\b", r"\boverfald\b",
    # tr / ru / ar / hi
    r"saldırı\w*", r"нападени\w+", r"\bизбит\w*", r"\bподжог\w*", r"\bподожг\w*", r"اعتداء", r"هجوم", r"حرق", r"हमला", r"मारपीट",
]))

# Process words: they only make an incident report when the title ALSO names
# the hate/extremism context ("neo-Nazi rally in X", "man jailed for racist ...").
_PROCESS = _rx("|".join([
    r"\barrest(?:ed|s)?\b", r"\bcharged\b", r"\bjailed\b", r"\bconvicted\b", r"\bsentenced\b", r"\bin court\b",
    r"\brally\b", r"\bmarch(?:ed)?\b", r"\bdemonstrat\w+", r"\bnazi salute\b", r"\bhitler salute\b",
    r"\bfestgenommen\b", r"\bverurteilt\b", r"\baufmarsch\b", r"\bdemo\b", r"\bkundgebung\b", r"\bprozess\b", r"\bfestnahme\b",
    r"\binterpell\w+", r"\bmis en examen\b", r"\bcondamné\w*", r"\bmanifestation\b",
    r"\bdetenid[oa]\b", r"\bcondenad[oa]\b", r"\barrestat[oa]\b", r"\bcondannat[oa]\b", r"\bpreso\b", r"\bpresos\b",
    r"\baangehouden\b", r"gözaltı", r"задержан\w*", r"اعتقال",
]))

# Hate / extremism / discrimination named outright.
_HATE_STRONG = _rx("|".join([
    r"\bracis[mt]\w*", r"\bracial(?:ly)?\b", r"xenophob\w*", r"anti-?semit\w*", r"islamophob\w*", r"anti-?muslim",
    r"anti-?black", r"anti-?asian", r"anti-?roma", r"antigypsyism", r"homophob\w*", r"transphob\w*", r"anti-?lgbt\w*",
    r"neo-?nazi\w*", r"\bnazis?\b", r"white supremac\w*", r"far[- ]right", r"extreme[- ]right", r"right-wing extrem\w*",
    r"hate crime", r"hate speech", r"\bswastikas?\b", r"\bnoose\b",
    r"\brassis\w+", r"rechtsextrem\w*", r"rechtsradikal\w*", r"fremdenfeind\w*", r"antisemit\w*", r"judenfeind\w*",
    r"islamfeind\w*", r"muslimfeind\w*", r"queerfeind\w*", r"neonazi\w*", r"hakenkreuz\w*", r"\bmenschenfeind\w*",
    r"volksverhetzung", r"reichsbürger", r"rechte gewalt", r"\brechts(?:motiviert|terror)\w*", r"\bantimuslim\w*",
    r"\bracis(?:me|te)s?\b", r"antis[eé]mit\w*", r"extr[eê]me[- ]droite", r"n[eé]onazi\w*", r"xénophob\w*", r"croix gammée",
    r"\bracist[ao]s?\b", r"\bracismo\b", r"xen[oó]fob\w*", r"islam[oó]fob\w*", r"extrema[- ]derecha", r"extrema[- ]direita",
    r"homof[oó]b\w*", r"neonazi\w*", r"neonazist\w*", r"inj[uú]ria racial", r"antissemit\w*",
    r"\brazzis\w+", r"neofasc\w+", r"\bantisemit\w*",
    r"\bracistisch\w*", r"\bextreemrechts\w*", r"\bracisme\b",
    r"\brasism\w*", r"\bfrämlingsfient\w*", r"\bracism\b",
    r"ırkçı\w*", r"nefret suçu", r"antisemit\w*",
    r"расист\w*", r"ксенофоб\w*", r"неонацист\w*", r"антисемит\w*", r"исламофоб\w*", r"ультраправ\w*",
    r"عنصري\w*", r"عنصرية", r"معاداة السامية", r"إسلاموفوبيا", r"جريمة كراهية", r"اليمين المتطرف",
    r"नस्लीय", r"नस्लवाद", r"घृणा अपराध",
]))

# People or places that are targeted. Alone they are just news topics
# ("migrants", "a mosque"); with a violent act in the headline they are victims.
_TARGET = _rx("|".join([
    r"\bmosques?\b", r"\bsynagogues?\b", r"\bjewish\b", r"\bmuslims?\b", r"\basylum\b", r"\brefugees?\b", r"\bmigrants?\b",
    r"\bimmigrants?\b", r"\bpeople of colou?r\b", r"\bblack (?:man|woman|teen|youth|student|family|men|women)\b",
    r"\bsikh\b", r"\bhindu temple\b", r"\bgurdwara\b", r"\bmandir\b",
    r"\bmoschee\w*", r"\bsynagoge\w*", r"\bgeflüchtet\w*", r"\bflüchtling\w*", r"\basylbewerber\w*", r"\bjüdisch\w*",
    r"\bmigranten?\b", r"\bmuslim\w*", r"\bunterkunft\b",
    r"\bmosquée\w*", r"\bsynagogue\b", r"\bréfugi[eé]\w*", r"\bmigrants?\b", r"\bjuif\w*", r"\bmusulman\w*",
    r"\bmezquita\b", r"\bsinagoga\b", r"\brefugiad\w+", r"\bmigrantes?\b", r"\bmoschea\b", r"\bebre[oi]\b", r"\bmusulman\w*",
    r"\bmoskee\b", r"\bvluchteling\w*", r"\bmoské\b", r"\bcami\b", r"\bgöçmen\w*", r"\bmülteci\w*",
    r"\bмигрант\w*", r"\bмечет\w*", r"\bбеженц\w*", r"مسجد", r"كنيس", r"لاجئ", r"مهاجر",
]))

# Things a specific report has and an essay does not.
_CONCRETE = _rx("|".join([
    r"\bpolice\b", r"\bofficers?\b", r"\bsuspects?\b", r"\binjur\w*", r"\bhospital", r"\bvictims?\b",
    r"\bwitness\w*", r"\bCCTV\b", r"\bman\b", r"\bwoman\b", r"\bteen(?:ager)?s?\b", r"\bboys?\b", r"\bgirls?\b",
    r"\bstudents?\b", r"\b\d{1,3}-year-old\b", r"\b(?:two|three|four|five|six|seven|eight|nine|ten|\d+) (?:men|women|people|youths)\b",
    r"\bmosque\b", r"\bsynagogue\b", r"\bgraveyard\b", r"\bcemetery\b", r"\bmemorial\b", r"\bschool\b", r"\bshop\b",
    r"\bbus\b", r"\btrain\b", r"\bstation\b", r"\bflag\b", r"\bbanner\b", r"\bgraffiti\b", r"\bswastikas?\b", r"\bnoose\b",
    r"\bpolizei\b", r"\bstaatsanwalt\w*", r"\bgericht\b", r"\btatverdächtig\w*", r"\bverletzt\w*", r"\bopfer\b", r"\bmann\b",
    r"\bfrau\b", r"\bjugendliche\w*", r"\bunterkunft\b", r"\bfriedhof\b", r"\bmoschee\b", r"\bsynagoge\b",
    r"\bpolicier\w*", r"\bgendarm\w*", r"\btribunal\b", r"\bblessé\w*", r"\bvictime\w*", r"\bhomme\b", r"\bfemme\b",
    r"\bpolicía\b", r"\bpolícia\b", r"\bguardia civil\b", r"\bherido\w*", r"\bferid[oa]s?\b", r"\bcarabinieri\b", r"\bquestura\b",
    r"\bpolitie\b", r"\bpolitiet\b", r"\bpoliisi\b",
    r"\bполици\w*", r"\bмужчин\w*", r"\bженщин\w*", r"شرطة", r"رجل", r"امرأة", r"पुलिस",
]))

# Things an incident report is not.
_NOT_INCIDENT_TITLE = _rx("|".join([
    r"^\s*(?:opinion|comment|analysis|editorial|commentary|op-?ed|column|essay|review|interview|podcast|video|watch|live|quiz|letters?)\b\s*[:|–—-]",
    r"^\s*(?:meinung|kommentar|analyse|standpunkt|gastbeitrag|interview|podcast|glosse|leitartikel|kolumne|rezension)\b\s*[:|–—-]",
    r"^\s*(?:opinión|opinion|tribune|chronique|éditorial|editorial|análise|opinião|commento|analisi|opinie)\b\s*[:|–—-]",
    r"\breview\s*[\u2013\u2014:-]", r"\bhow (?:to|we|can|do|should)\b", r"\bwhy (?:we|the|do|are|is|it)\b", r"\bwhat (?:is|are|to|you|we)\b", r"\bwhat's\b",
    r"\bexplained\b", r"\bexplainer\b", r"\bthe case for\b", r"\bthe case against\b", r"\byou need to know\b", r"\bq&a\b",
    r"\bcalls? (?:on|for)\b", r"\burges?\b", r"\bwelcomes?\b", r"\bdemands?\b", r"\bmust (?:act|do|be|stop)\b", r"\bshould\b",
    r"\bstatement\b", r"\bposition paper\b", r"\bpolicy\b", r"\bconsultation\b", r"\bnew report\b", r"\bannual report\b",
    r"\bsurvey\b", r"\bstudy\b", r"\bresearch finds\b", r"\bpoll\b", r"\bfigures show\b", r"\bstatistics\b", r"\bdata shows?\b",
    r"\bdonat", r"\bfundrais", r"\bsupport us\b", r"\bgive now\b", r"\bsign (?:the )?petition\b", r"\bpetition\b",
    r"\bjoin us\b", r"\bregister\b", r"\bwebinar\b", r"\bconference\b", r"\bworkshop\b", r"\bsave the date\b",
    r"\bcall for (?:papers|applications|proposals)\b", r"\bjob\b", r"\bvacanc", r"\bwe(?:'re| are) hiring\b", r"\bnewsletter\b",
    r"\bevent\b", r"\bexhibition\b", r"\bfilm screening\b", r"\bbook launch\b", r"\blaunch(?:es|ed)?\b", r"\bappeal\b",
    r"\bfordert\b", r"\bforderung\b", r"\bappelliert\b", r"\bbegrüßt\b", r"\bstellungnahme\b", r"\bpressemitteilung\b",
    r"\bstudie\b", r"\bumfrage\b", r"\bstatistik\b", r"\bbilanz\b", r"\bjahresbericht\b", r"\bspende", r"\bveranstaltung\b",
    r"\banmeldung\b", r"\bausstellung\b", r"\blesung\b", r"\bfachtag\b", r"\bseminar\b", r"\bstellenausschreibung\b", r"\bwie (?:wir|man|kann)\b",
    r"\bwarum\b", r"\bwas (?:ist|sind|wir|man)\b", r"\bpourquoi\b", r"\bcomment\b", r"\bappelle\b", r"\bdemande\b", r"\bétude\b",
    r"\bsondage\b", r"\brapport annuel\b", r"\bcommuniqué\b", r"\bdon\b", r"\bconférence\b", r"\bpor qué\b", r"\bcómo\b",
    r"\binforme anual\b", r"\bencuesta\b", r"\bconvoca\b", r"\bperché\b", r"\bcome\b.*\?", r"\bsondaggio\b", r"\brapporto annuale\b",
]))
_NOT_INCIDENT_URL = _rx(r"/(?:opinion|opinions|comment|commentisfree|meinung|kommentar|editorial|blog|blogs|podcast|podcasts|"
                        r"video|videos|events?|veranstaltungen|termine|jobs?|karriere|donate|spenden|shop|"
                        r"opinión|tribune|chroniques?|opiniao|opinione|opinie|analysis|analyse|features?)/")

# Acts that are specific even without another concrete cue.
_STRONG = _rx(r"\barson\b|\bstabb|\bdesecrat|\bswastika|\bgraffiti\b|brandanschlag|hakenkreuz|schändung|geschändet|"
              r"profanation|profanaci|profanazione|incendie criminel|firebomb|\btorched\b|\bnoose\b|\bmurder")


def looks_like_incident(title: str, summary: str = "", url: str = "", mode: str = "news") -> bool:
    """Heuristic: is this feed item a report of one specific incident?

    The HEADLINE must state an act (attacked, set on fire, vandalised, abused,
    desecrated ...), because an essay or a policy statement states a topic, not
    an act, and the summary is full of context words that would let them in.
    The hate/extremism context may come from headline or summary. Process words
    (arrested, jailed, rally, march) only count when the headline itself names
    the hate context. mode 'chronicle' (a source that lists nothing but
    incidents) waives the context requirement; every other rule still applies."""
    title = clean_text(title[:TITLE_MAX * 4])[:TITLE_MAX]     # bound the input BEFORE any regex runs
    summary = (summary or "")[:SUMMARY_MAX]
    if len(title) < 15 or title.rstrip().endswith("?"):
        return False
    if _NOT_INCIDENT_TITLE.search(title):
        return False
    if url and _NOT_INCIDENT_URL.search(urlparse(url).path + "/"):
        return False
    text = f"{title} {summary}"
    act = bool(_ACT.search(title))
    process = bool(_PROCESS.search(title))
    if mode == "chronicle":
        specific = act or process
    else:
        hate_title = bool(_HATE_STRONG.search(title))
        hate_any = hate_title or bool(_HATE_STRONG.search(summary))
        target_any = bool(_TARGET.search(text))
        specific = (act and (hate_any or target_any)) or (process and hate_title)
        # A target alone is a topic, not a motive: an act against "a migrant"
        # needs at least a concrete cue (police, victim, injured ...) as well.
        if specific and not hate_any:
            specific = bool(_CONCRETE.search(text))
    if not specific:
        return False
    concrete = bool(_CONCRETE.search(text)) or geolocate.from_offline(title) is not None
    return concrete or bool(_STRONG.search(text))


def hate_category(text: str) -> tuple[str, str]:
    """(category slug, reason) from the hate context, for items the keyword
    classifier in lawref did not recognise (other languages, other wording)."""
    t = text.lower()
    table = [
        (r"anti-?semit|antisemit|judenfeind|synagog|jewish|antisémit|антисемит|معاداة السامية|كنيس", "antisemitism", "antisemitic incident reported"),
        (r"islamophob|anti-?muslim|muslimfeind|islamfeind|\bmosque|moschee|mosquée|mezquita|moschea|moskee|мечет|إسلاموفوبيا|مسجد", "islamophobia", "anti-Muslim incident reported"),
        (r"homophob|transphob|queerfeind|anti-?lgbt|homof[oó]b", "homophobia_transphobia", "homophobic / transphobic incident reported"),
        (r"neo-?nazi|\bnazi|neonazi|swastika|hakenkreuz|croix gammée|white supremac|свастик|неонацист", "neo_nazi", "neo-Nazi activity reported"),
        (r"xenophob|fremdenfeind|xénophob|xenofob|asylum|asyl|refugee|geflüchtet|migrant|réfugi", "xenophobia", "xenophobic incident reported"),
        (r"racis|rassis|racial|racist|raciste|razzis|ırkçı|расист|عنصري|नस्लीय", "racism", "racist incident reported"),
    ]
    for rx, cat, reason in table:
        if re.search(rx, t):
            return cat, f"Automated signal: {reason} in a news feed (needs review)"
    return "other", "Automated signal: hate-related incident reported in a news feed (needs review)"


# --------------------------------------------------------------------------- #
# De-duplication                                                               #
# --------------------------------------------------------------------------- #

TITLE_DEDUPE_WINDOW = 3 * 86400
_NOT_A_BLOCKER = ("dismissed", "irrelevant")


class Deduper:
    """Is this feed item already on the map?

    * The same URL always counts, whatever the status of the earlier row (a URL
      is one article; insert_report refuses it anyway).
    * The same normalised headline counts only when the earlier item is within
      3 days of this one AND, if both name a place, it is the same place: a
      headline like "Mosque attacked" is a different incident in a different
      town next month. A dismissed or irrelevant earlier item never blocks a
      new one by title, or one dismissed lead would hide that headline forever.
    """

    def __init__(self, rows: list[dict[str, Any]]):
        self.urls: set[str] = set()
        self.titles: dict[str, list[tuple[float, Optional[str]]]] = {}
        for r in rows:
            if r.get("url"):
                self.urls.add(normalize_url(r["url"]))
            if r.get("title") and r.get("status") not in _NOT_A_BLOCKER:
                self.titles.setdefault(normalize_title(r["title"]), []).append((r.get("ts") or 0, r.get("place")))

    def seen(self, url: str, title_key: str, ts: Optional[int], place: Optional[str]) -> bool:
        if normalize_url(url) in self.urls:
            return True
        when = ts if ts is not None else time.time()
        for old_ts, old_place in self.titles.get(title_key, ()):
            if abs(when - old_ts) <= TITLE_DEDUPE_WINDOW and (not (place and old_place) or place == old_place):
                return True
        return False

    def add(self, url: str, title_key: str, ts: Optional[int], place: Optional[str]) -> None:
        self.urls.add(normalize_url(url))
        self.titles.setdefault(title_key, []).append((ts if ts is not None else time.time(), place))


# --------------------------------------------------------------------------- #
# Feed list                                                                    #
# --------------------------------------------------------------------------- #

def load_feeds() -> list[dict[str, Any]]:
    """Feed list from DXMAP_RSS_URLS, else from FEEDS_FILE. Disabled feeds dropped."""
    urls = os.environ.get("DXMAP_RSS_URLS", "").strip()
    if urls:
        return [{"id": hashlib.sha1(u.encode()).hexdigest()[:8], "url": u.strip(),
                 "publisher": urlparse(u.strip()).netloc, "mode": "news", "region": "", "lang": ""}
                for u in urls.split(",") if u.strip()]
    try:
        with open(FEEDS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [f for f in data.get("feeds", []) if f.get("url") and f.get("enabled", True)]


# --------------------------------------------------------------------------- #
# Fetching                                                                     #
# --------------------------------------------------------------------------- #

_STATE: dict[str, dict[str, Any]] = {}      # feed url -> etag/last_modified/next_at/fails/ttl
_ROBOTS: dict[str, tuple[float, Optional[RobotFileParser]]] = {}   # host -> (fetched_at, parser|None=allow all)


def reset_state() -> None:
    _STATE.clear()
    _ROBOTS.clear()


class FetchRefused(Exception):
    """A request we will not make or not follow (redirect, private address, too big)."""


def _check_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise FetchRefused(f"unsupported URL {url!r}")
    host = p.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise FetchRefused(f"local host {host}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if not ip.is_global:
        raise FetchRefused(f"non-public address {host}")


async def _get_capped(client: httpx.AsyncClient, url: str, headers: dict, cap: int) -> tuple[int, dict, bytes]:
    """GET without following redirects. A 3xx is an error (a redirect could
    point an outside feed at 127.0.0.1 or a cloud metadata address, and we
    keep the feed list on final URLs instead). The body is streamed and the
    request abandoned once it passes `cap` bytes."""
    _check_url(url)
    async with client.stream("GET", url, headers=headers, follow_redirects=False) as r:
        if r.status_code in (301, 302, 303, 307, 308):
            log.warning("rss: %s answered %s, redirects are not followed (Location: %s)",
                        url, r.status_code, r.headers.get("location", "")[:120])
            raise FetchRefused(f"redirect {r.status_code}")
        declared = r.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > cap:
            raise FetchRefused("body too large")
        buf = bytearray()
        async for chunk in r.aiter_bytes():
            buf += chunk
            if len(buf) > cap:
                raise FetchRefused("body too large")
        return r.status_code, dict(r.headers), bytes(buf)


async def robots_allows(client: httpx.AsyncClient, url: str) -> Optional[bool]:
    """True/False per robots.txt; None when robots.txt could not be read right
    now (the caller skips the feed this round rather than guessing)."""
    p = urlparse(url)
    host = f"{p.scheme}://{p.netloc}"
    now = time.time()
    cached = _ROBOTS.get(host)
    if cached is None or now - cached[0] > ROBOTS_TTL:
        parser: Optional[RobotFileParser] = None
        try:
            status, _h, body = await _get_capped(client, f"{host}/robots.txt",
                                                 {"User-Agent": RSS_USER_AGENT}, ROBOTS_MAX_BYTES)
        except Exception:
            return None
        if status in (401, 403):
            parser = RobotFileParser()
            parser.parse(["User-agent: *", "Disallow: /"])
        elif status == 200:
            parser = RobotFileParser()
            parser.parse(body.decode("utf-8", "replace").splitlines())
        elif 400 <= status < 500:
            parser = None          # no robots.txt: everything allowed
        else:
            return None            # 5xx: try again later
        _ROBOTS[host] = (now, parser)
        cached = _ROBOTS[host]
    parser = cached[1]
    return True if parser is None else parser.can_fetch(RSS_USER_AGENT, url)


def _backoff(st: dict[str, Any], now: float, retry_after: Optional[float] = None) -> None:
    """Exponential: 5 min, 10, 20 ... capped at 6 h; a Retry-After wins (also capped)."""
    st["fails"] = st.get("fails", 0) + 1
    delay = retry_after if retry_after else 300 * 2 ** (st["fails"] - 1)
    st["next_at"] = now + min(max(delay, 60), MAX_BACKOFF)


async def fetch_feed(client: httpx.AsyncClient, feed: dict[str, Any],
                     now: Optional[float] = None) -> Optional[dict[str, Any]]:
    """One polite fetch, bounded by a wall-clock deadline (a host that trickles
    bytes cannot hold a worker). Returns the parsed feed, or None when nothing
    new (not due yet, 304, disallowed, error). Never raises."""
    url = feed["url"]
    st = _STATE.setdefault(url, {})
    now = time.time() if now is None else now
    if st.get("next_at", 0) > now:
        return None
    try:
        return await asyncio.wait_for(_fetch_feed_inner(client, feed, st, now), FEED_DEADLINE_S)
    except Exception:       # includes the deadline (TimeoutError)
        _backoff(st, now)
        return None


async def _fetch_feed_inner(client: httpx.AsyncClient, feed: dict[str, Any], st: dict[str, Any],
                            now: float) -> Optional[dict[str, Any]]:
    url = feed["url"]
    ok = await robots_allows(client, url)
    if ok is None:
        _backoff(st, now)
        return None
    if ok is False:
        st["next_at"] = now + ROBOTS_TTL
        st["blocked"] = True
        return None
    headers = {"User-Agent": RSS_USER_AGENT,
               "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8"}
    if st.get("etag"):
        headers["If-None-Match"] = st["etag"]
    if st.get("last_modified"):
        headers["If-Modified-Since"] = st["last_modified"]
    status, rh, body = await _get_capped(client, url, headers, MAX_BYTES)
    if status == 304:
        st["fails"] = 0
        st["next_at"] = now + max(MIN_INTERVAL, (st.get("ttl") or 0) * 60)
        return None
    if status in (429, 503):
        ra = rh.get("retry-after", "")
        _backoff(st, now, float(ra) if ra.isdigit() else None)
        return None
    if status != 200:
        _backoff(st, now)
        return None
    parsed = parse_feed(body)
    st.update(fails=0, etag=rh.get("etag"), last_modified=rh.get("last-modified"),
              ttl=parsed["ttl_minutes"],
              next_at=now + max(MIN_INTERVAL, (parsed["ttl_minutes"] or 0) * 60))
    st.pop("blocked", None)
    return parsed


def feed_items(feed: dict[str, Any], parsed: dict[str, Any], now: Optional[int] = None) -> list[dict[str, Any]]:
    """Parsed feed -> adapter items: only recent, only real incidents, newest
    first, at most MAX_ITEMS_PER_FEED. Nothing but headline, link, publisher,
    date and a short snippet leaves this function."""
    now = int(time.time()) if now is None else now
    publisher = feed.get("publisher") or feed.get("name") or urlparse(feed["url"]).netloc
    mode = feed.get("mode", "news")
    out = []
    for it in sorted(parsed["items"], key=lambda i: i["date"] or 0, reverse=True):
        if len(out) >= MAX_ITEMS_PER_FEED:
            break
        link = normalize_url(it["link"]) if it["link"] else ""
        if not link.lower().startswith(("http://", "https://")) or not it["title"]:
            continue
        if it["date"] is not None and (now - it["date"]) > MAX_AGE_DAYS * 86400:
            continue
        if not looks_like_incident(it["title"], it["summary"], link, mode):
            continue
        cat, reason = hate_category(f"{it['title']} {it['summary']}")
        date = min(it["date"], now) if it["date"] else None
        out.append({
            "external_id": "rss_" + hashlib.sha1(link.encode()).hexdigest()[:20],
            "title": it["title"][:300],
            "body": make_snippet(it["summary"]),
            "url": link,
            "category": "rss",
            "source_name": publisher[:120],
            "occurred_at": date,
            "prefilter": {"category": cat, "reason": reason},
            "_dedupe_title": normalize_title(it["title"]),
        })
    return out
