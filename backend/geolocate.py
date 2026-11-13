"""
Turn free text into coordinates.

Two-stage, cheapest first:
  1. Offline gazetteer of major world cities  -> instant, no network.
  2. OSM Nominatim geocoding (free)           -> for anything the gazetteer
     misses. Rate-limited to <=1 req/s per Nominatim's usage policy, with a
     descriptive User-Agent as they require.

If neither resolves, we return None and the report is stored unlocated.

The offline stage has two layers: the small hand-kept GAZETTEER below (German
towns, US states, Bundeslaender, country centres) and a worldwide table of
~68k place names built from GeoNames (backend/data/world_places.tsv, CC BY 4.0,
see scripts/build_world_gazetteer.py). `from_offline()` combines them.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import httpx

# A compact gazetteer. Deliberately small and offline: it covers the common
# hits so most reports resolve without any network call. Extend freely.
# name (lowercased) -> (lat, lon, display)
GAZETTEER: dict[str, tuple[float, float, str]] = {
    "london": (51.5074, -0.1278, "London, UK"),
    "manchester": (53.4808, -2.2426, "Manchester, UK"),
    "birmingham": (52.4862, -1.8904, "Birmingham, UK"),
    "edinburgh": (55.9533, -3.1883, "Edinburgh, UK"),
    "dublin": (53.3498, -6.2603, "Dublin, IE"),
    "new york": (40.7128, -74.0060, "New York, US"),
    "los angeles": (34.0522, -118.2437, "Los Angeles, US"),
    "chicago": (41.8781, -87.6298, "Chicago, US"),
    "houston": (29.7604, -95.3698, "Houston, US"),
    "san francisco": (37.7749, -122.4194, "San Francisco, US"),
    "seattle": (47.6062, -122.3321, "Seattle, US"),
    "boston": (42.3601, -71.0589, "Boston, US"),
    "miami": (25.7617, -80.1918, "Miami, US"),
    "toronto": (43.6532, -79.3832, "Toronto, CA"),
    "vancouver": (49.2827, -123.1207, "Vancouver, CA"),
    "paris": (48.8566, 2.3522, "Paris, FR"),
    "berlin": (52.5200, 13.4050, "Berlin, DE"),
    "madrid": (40.4168, -3.7038, "Madrid, ES"),
    "barcelona": (41.3874, 2.1686, "Barcelona, ES"),
    "rome": (41.9028, 12.4964, "Rome, IT"),
    "amsterdam": (52.3676, 4.9041, "Amsterdam, NL"),
    "lisbon": (38.7223, -9.1393, "Lisbon, PT"),
    "athens": (37.9838, 23.7275, "Athens, GR"),
    "istanbul": (41.0082, 28.9784, "Istanbul, TR"),
    "moscow": (55.7558, 37.6173, "Moscow, RU"),
    "dubai": (25.2048, 55.2708, "Dubai, AE"),
    "cairo": (30.0444, 31.2357, "Cairo, EG"),
    "lagos": (6.5244, 3.3792, "Lagos, NG"),
    "nairobi": (-1.2921, 36.8219, "Nairobi, KE"),
    "johannesburg": (-26.2041, 28.0473, "Johannesburg, ZA"),
    "mumbai": (19.0760, 72.8777, "Mumbai, IN"),
    "delhi": (28.7041, 77.1025, "Delhi, IN"),
    "bangalore": (12.9716, 77.5946, "Bangalore, IN"),
    "singapore": (1.3521, 103.8198, "Singapore, SG"),
    "hong kong": (22.3193, 114.1694, "Hong Kong, HK"),
    "tokyo": (35.6762, 139.6503, "Tokyo, JP"),
    "seoul": (37.5665, 126.9780, "Seoul, KR"),
    "sydney": (-33.8688, 151.2093, "Sydney, AU"),
    "melbourne": (-37.8136, 144.9631, "Melbourne, AU"),
    "auckland": (-36.8485, 174.7633, "Auckland, NZ"),
    "sao paulo": (-23.5505, -46.6333, "Sao Paulo, BR"),
    "rio de janeiro": (-22.9068, -43.1729, "Rio de Janeiro, BR"),
    "mexico city": (19.4326, -99.1332, "Mexico City, MX"),
    "buenos aires": (-34.6037, -58.3816, "Buenos Aires, AR"),
    # --- more cities ---
    "washington": (38.9072, -77.0369, "Washington, DC"),
    "philadelphia": (39.9526, -75.1652, "Philadelphia, US"),
    "atlanta": (33.7490, -84.3880, "Atlanta, US"),
    "dallas": (32.7767, -96.7970, "Dallas, US"),
    "denver": (39.7392, -104.9903, "Denver, US"),
    "phoenix": (33.4484, -112.0740, "Phoenix, US"),
    "portland": (45.5152, -122.6784, "Portland, US"),
    "detroit": (42.3314, -83.0458, "Detroit, US"),
    "glasgow": (55.8642, -4.2518, "Glasgow, UK"),
    "leeds": (53.8008, -1.5491, "Leeds, UK"),
    "liverpool": (53.4084, -2.9916, "Liverpool, UK"),
    "munich": (48.1351, 11.5820, "Munich, DE"),
    "hamburg": (53.5511, 9.9937, "Hamburg, DE"),
    "milan": (45.4642, 9.1900, "Milan, IT"),
    "vienna": (48.2082, 16.3738, "Vienna, AT"),
    "warsaw": (52.2297, 21.0122, "Warsaw, PL"),
    "kyiv": (50.4501, 30.5234, "Kyiv, UA"),
    "kiev": (50.4501, 30.5234, "Kyiv, UA"),
    "tel aviv": (32.0853, 34.7818, "Tel Aviv, IL"),
    "gaza": (31.5017, 34.4668, "Gaza"),
    "beijing": (39.9042, 116.4074, "Beijing, CN"),
    "shanghai": (31.2304, 121.4737, "Shanghai, CN"),
    "bangkok": (13.7563, 100.5018, "Bangkok, TH"),
    "jakarta": (-6.2088, 106.8456, "Jakarta, ID"),
    "manila": (14.5995, 120.9842, "Manila, PH"),
    "karachi": (24.8607, 67.0011, "Karachi, PK"),
    "chennai": (13.0827, 80.2707, "Chennai, IN"),
    "kolkata": (22.5726, 88.3639, "Kolkata, IN"),
    # --- US states (centroids) ---
    "california": (36.7783, -119.4179, "California, US"),
    "texas": (31.9686, -99.9018, "Texas, US"),
    "florida": (27.6648, -81.5158, "Florida, US"),
    "new york state": (42.9538, -75.5268, "New York State, US"),
    "washington state": (47.7511, -120.7401, "Washington State, US"),
    "arizona": (34.0489, -111.0937, "Arizona, US"),
    "colorado": (39.5501, -105.7821, "Colorado, US"),
    "oregon": (43.8041, -120.5542, "Oregon, US"),
    "nevada": (38.8026, -116.4194, "Nevada, US"),
    "louisiana": (30.9843, -91.9623, "Louisiana, US"),
    # --- countries (centroids) ---
    "united states": (39.8283, -98.5795, "United States"),
    "usa": (39.8283, -98.5795, "United States"),
    "ukraine": (48.3794, 31.1656, "Ukraine"),
    "russia": (61.5240, 105.3188, "Russia"),
    "china": (35.8617, 104.1954, "China"),
    "india": (20.5937, 78.9629, "India"),
    "pakistan": (30.3753, 69.3451, "Pakistan"),
    "israel": (31.0461, 34.8516, "Israel"),
    "palestine": (31.9522, 35.2332, "Palestine"),
    "iran": (32.4279, 53.6880, "Iran"),
    "france": (46.2276, 2.2137, "France"),
    "germany": (51.1657, 10.4515, "Germany"),
    "spain": (40.4637, -3.7492, "Spain"),
    "italy": (41.8719, 12.5674, "Italy"),
    "japan": (36.2048, 138.2529, "Japan"),
    "australia": (-25.2744, 133.7751, "Australia"),
    "canada": (56.1304, -106.3468, "Canada"),
    "brazil": (-14.2350, -51.9253, "Brazil"),
    "mexico": (23.6345, -102.5528, "Mexico"),
    "nigeria": (9.0820, 8.6753, "Nigeria"),
    "sudan": (12.8628, 30.2176, "Sudan"),
    "turkey": (38.9637, 35.2433, "Turkey"),
    "greece": (39.0742, 21.8243, "Greece"),
    "ireland": (53.4129, -8.2439, "Ireland"),
    "scotland": (56.4907, -4.2026, "Scotland, UK"),
    # --- Germany: major cities (primary focus) ---
    "berlin": (52.5200, 13.4050, "Berlin, DE"),
    "hamburg": (53.5511, 9.9937, "Hamburg, DE"),
    "munich": (48.1351, 11.5820, "München, DE"),
    "münchen": (48.1351, 11.5820, "München, DE"),
    "muenchen": (48.1351, 11.5820, "München, DE"),
    "cologne": (50.9375, 6.9603, "Köln, DE"),
    "köln": (50.9375, 6.9603, "Köln, DE"),
    "koeln": (50.9375, 6.9603, "Köln, DE"),
    "frankfurt": (50.1109, 8.6821, "Frankfurt am Main, DE"),
    "stuttgart": (48.7758, 9.1829, "Stuttgart, DE"),
    "düsseldorf": (51.2277, 6.7735, "Düsseldorf, DE"),
    "duesseldorf": (51.2277, 6.7735, "Düsseldorf, DE"),
    "dortmund": (51.5136, 7.4653, "Dortmund, DE"),
    "essen": (51.4556, 7.0116, "Essen, DE"),
    "leipzig": (51.3397, 12.3731, "Leipzig, DE"),
    "dresden": (51.0504, 13.7373, "Dresden, DE"),
    "bremen": (53.0793, 8.8017, "Bremen, DE"),
    "hannover": (52.3759, 9.7320, "Hannover, DE"),
    "hanover": (52.3759, 9.7320, "Hannover, DE"),
    "nuremberg": (49.4521, 11.0767, "Nürnberg, DE"),
    "nürnberg": (49.4521, 11.0767, "Nürnberg, DE"),
    "nuernberg": (49.4521, 11.0767, "Nürnberg, DE"),
    "duisburg": (51.4344, 6.7623, "Duisburg, DE"),
    "bochum": (51.4818, 7.2162, "Bochum, DE"),
    "wuppertal": (51.2562, 7.1508, "Wuppertal, DE"),
    "bielefeld": (52.0302, 8.5325, "Bielefeld, DE"),
    "bonn": (50.7374, 7.0982, "Bonn, DE"),
    "münster": (51.9607, 7.6261, "Münster, DE"),
    "muenster": (51.9607, 7.6261, "Münster, DE"),
    "karlsruhe": (49.0069, 8.4037, "Karlsruhe, DE"),
    "mannheim": (49.4875, 8.4660, "Mannheim, DE"),
    "augsburg": (48.3705, 10.8978, "Augsburg, DE"),
    "wiesbaden": (50.0782, 8.2398, "Wiesbaden, DE"),
    "chemnitz": (50.8278, 12.9214, "Chemnitz, DE"),
    "magdeburg": (52.1205, 11.6276, "Magdeburg, DE"),
    "halle": (51.4969, 11.9688, "Halle (Saale), DE"),
    "erfurt": (50.9848, 11.0299, "Erfurt, DE"),
    "rostock": (54.0924, 12.0991, "Rostock, DE"),
    "kassel": (51.3127, 9.4797, "Kassel, DE"),
    "cottbus": (51.7563, 14.3329, "Cottbus, DE"),
    "gera": (50.8809, 12.0828, "Gera, DE"),
    "zwickau": (50.7189, 12.4961, "Zwickau, DE"),
    "plauen": (50.4947, 12.1379, "Plauen, DE"),
    "bautzen": (51.1814, 14.4238, "Bautzen, DE"),
    "freital": (51.0000, 13.6500, "Freital, DE"),
    "heidenau": (50.9800, 13.8600, "Heidenau, DE"),
    "solingen": (51.1652, 7.0671, "Solingen, DE"),
    "hanau": (50.1327, 8.9166, "Hanau, DE"),
    "halle-neustadt": (51.4800, 11.9200, "Halle-Neustadt, DE"),
    # --- Germany: the 16 Bundesländer (centroids) ---
    "saxony": (51.1045, 13.2017, "Sachsen, DE"),
    "sachsen": (51.1045, 13.2017, "Sachsen, DE"),
    "thuringia": (50.9013, 11.0177, "Thüringen, DE"),
    "thüringen": (50.9013, 11.0177, "Thüringen, DE"),
    "thueringen": (50.9013, 11.0177, "Thüringen, DE"),
    "brandenburg": (52.4125, 12.5316, "Brandenburg, DE"),
    "bavaria": (48.7904, 11.4979, "Bayern, DE"),
    "bayern": (48.7904, 11.4979, "Bayern, DE"),
    "saxony-anhalt": (51.9503, 11.6923, "Sachsen-Anhalt, DE"),
    "sachsen-anhalt": (51.9503, 11.6923, "Sachsen-Anhalt, DE"),
    "mecklenburg-vorpommern": (53.6127, 12.4296, "Mecklenburg-Vorpommern, DE"),
    "lower saxony": (52.6367, 9.8451, "Niedersachsen, DE"),
    "niedersachsen": (52.6367, 9.8451, "Niedersachsen, DE"),
    "north rhine-westphalia": (51.4332, 7.6616, "Nordrhein-Westfalen, DE"),
    "nordrhein-westfalen": (51.4332, 7.6616, "Nordrhein-Westfalen, DE"),
    "hesse": (50.6521, 9.1624, "Hessen, DE"),
    "hessen": (50.6521, 9.1624, "Hessen, DE"),
    "baden-württemberg": (48.6616, 9.3501, "Baden-Württemberg, DE"),
    "baden-wuerttemberg": (48.6616, 9.3501, "Baden-Württemberg, DE"),
    "rhineland-palatinate": (49.9129, 7.4530, "Rheinland-Pfalz, DE"),
    "rheinland-pfalz": (49.9129, 7.4530, "Rheinland-Pfalz, DE"),
    "saarland": (49.3964, 7.0230, "Saarland, DE"),
    "schleswig-holstein": (54.2194, 9.6961, "Schleswig-Holstein, DE"),
    "germany": (51.1657, 10.4515, "Germany"),
    "deutschland": (51.1657, 10.4515, "Germany"),
}

# Longest names first so "new york" wins over a stray "york" if we add one.
_SORTED_NAMES = sorted(GAZETTEER.keys(), key=len, reverse=True)

_NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Nominatim usage policy: identifying User-Agent, max 1 request/second, cache.
_UA = os.environ.get("DXMAP_GEO_UA", "dxmap-agent (+https://map.nabilvs.com)")
_NOMINATIM_MIN_INTERVAL = 1.1
_last_nominatim_call = 0.0
_nominatim_lock = threading.Lock()
# Answers (including "nothing found") are remembered for the life of the process
# so the same place name is never asked for twice.
_NOMINATIM_CACHE: "OrderedDict[str, Optional[tuple[float, float, str]]]" = OrderedDict()
_NOMINATIM_CACHE_MAX = 5000

# Global by default. Set DXMAP_GEO_COUNTRY="de" (or any ISO country code)
# to restrict Nominatim geocoding to one country if you want to narrow focus.
_GEO_COUNTRY = os.environ.get("DXMAP_GEO_COUNTRY", "").strip()


# Generous bounding box around German territory, used to keep the map focused.
_DE_BOX = {"min_lat": 47.20, "max_lat": 55.10, "min_lon": 5.80, "max_lon": 15.10}


def in_germany(lat: float, lon: float) -> bool:
    """True if coordinates fall within the German bounding box."""
    return (_DE_BOX["min_lat"] <= lat <= _DE_BOX["max_lat"] and
            _DE_BOX["min_lon"] <= lon <= _DE_BOX["max_lon"])


def from_gazetteer(text: str) -> Optional[tuple[float, float, str]]:
    """Return (lat, lon, place) for the first known city mentioned, else None."""
    if not text:
        return None
    low = text.lower()
    for name in _SORTED_NAMES:
        # Word-boundary match so 'romerica' doesn't match 'rome'.
        if re.search(rf"\b{re.escape(name)}\b", low):
            lat, lon, disp = GAZETTEER[name]
            return lat, lon, disp
    return None


def coarsen(lat: float, lon: float) -> tuple[float, float]:
    """Round to two decimals (about a kilometre): scraped text that names a
    street address must not become a house-level pin on a public map."""
    return round(lat, 2), round(lon, 2)


class NominatimBusy(Exception):
    """Too many callers already waiting for the one-per-second slot."""


_MAX_WAITERS = 8
_waiting = 0
_waiting_lock = threading.Lock()


def nominatim_search(text: str, limit: int = 1, lang: Optional[str] = None,
                     timeout: float = 8.0) -> Optional[list[dict]]:
    """
    THE one place this process talks to Nominatim (the scraper's geocoder and
    the /api/geocode relay both come through here). Usage policy: never more
    than one request per second for the whole process (serialised under a lock
    across threads), identifying User-Agent, a process-wide cache so a query is
    asked once. At most _MAX_WAITERS callers may queue for the slot; more get
    NominatimBusy at once instead of tying up worker threads.
    Returns the raw result list, [] for "nothing found", None on a failure.
    """
    global _last_nominatim_call, _waiting
    if not text or len(text.strip()) < 3:
        return None
    key = f"{' '.join(text.lower().split())}|{limit}|{lang or ''}"
    if key in _NOMINATIM_CACHE:
        _NOMINATIM_CACHE.move_to_end(key)
        return _NOMINATIM_CACHE[key]
    with _waiting_lock:
        if _waiting >= _MAX_WAITERS:
            raise NominatimBusy()
        _waiting += 1
    try:
        with _nominatim_lock:
            if key in _NOMINATIM_CACHE:          # the caller before us asked the same thing
                return _NOMINATIM_CACHE[key]
            elapsed = time.time() - _last_nominatim_call
            if elapsed < _NOMINATIM_MIN_INTERVAL:
                time.sleep(_NOMINATIM_MIN_INTERVAL - elapsed)
            result: Optional[list[dict]] = None
            try:
                params: dict = {"q": text, "format": "json", "limit": limit}
                if lang:
                    params["accept-language"] = lang
                if _GEO_COUNTRY:
                    params["countrycodes"] = _GEO_COUNTRY
                resp = httpx.get(_NOMINATIM, params=params, headers={"User-Agent": _UA}, timeout=timeout)
                _last_nominatim_call = time.time()
                resp.raise_for_status()
                result = list(resp.json())
            except Exception:
                # Network hiccup / rate limit / bad response: do not cache, it may be transient.
                _last_nominatim_call = time.time()
                return None
            _NOMINATIM_CACHE[key] = result
            while len(_NOMINATIM_CACHE) > _NOMINATIM_CACHE_MAX:
                _NOMINATIM_CACHE.popitem(last=False)
            return result
    finally:
        with _waiting_lock:
            _waiting -= 1


def from_nominatim(text: str, timeout: float = 8.0) -> Optional[tuple[float, float, str]]:
    """One coarsened (about 1 km) hit for a place name, or None."""
    try:
        data = nominatim_search(text, 1, None, timeout)
    except NominatimBusy:
        return None
    if data:
        hit = data[0]
        lat, lon = coarsen(float(hit["lat"]), float(hit["lon"]))
        return lat, lon, hit.get("display_name", text)
    return None


# --------------------------------------------------------------------------- #
# Worldwide offline layer                                                      #
# --------------------------------------------------------------------------- #

_WORLD_PATH = Path(__file__).with_name("data") / "world_places.tsv"
# key -> candidates [(lat, lon, display, population, kind, country code)], biggest first
_WORLD: Optional[dict[str, list[tuple[float, float, str, int, str, str]]]] = None
_COUNTRY_NAMES: dict[str, set[str]] = {}          # country code -> lowercase names to look for in the text
# Letters, plus the combining marks of Indic and Thai scripts (which \w does not
# count as letters, so Hindi place names would otherwise be cut into pieces).
_LETTER = r"(?:[^\W\d_]|[\u0300-\u036f\u0900-\u0dff\u0e00-\u0e7f])"
_WORD_RE = re.compile(rf"{_LETTER}+(?:['\u2019\-]{_LETTER}+)*", re.UNICODE)
_MAX_NGRAM = 4
# A bare one-word city name is only trusted when the town is a large one, or
# when a locating word ("in", "near", "bei", "à", "en" ...) stands right before
# it. Otherwise ordinary words that are also towns ("Ende", "Man", "Mitte",
# "reading", "mobile") would pin posts to them. This was measured on real posts.
_MIN_POP_BARE = 1_000_000
_MIN_POP_MULTIWORD = 50_000
# Words that, right before a name, mean "at this place". Deliberately without
# the one-letter and article-like ones ("a", "na", "no", "da", "w") that sit in
# front of any capitalised word ("a Anna", "no Mustang").
_LOCATING = frozenset((
    "in near at outside from across around to into of bei im nach aus von vor "
    "à au aux en dans près chez de du desde hacia cerca em nel nella "
    "vicino bij uit naar från til в во из في من إلى"
).split())
# One-letter / article-like words that often, but not always, mean "at": they
# relax the size limit to cities of 500k or more ("a Napoli", "w Warszawie").
_WEAK_LOCATING = frozenset("a na no da w we".split())
_MIN_POP_WEAK = 500_000
# Also a common noun or a people's name: only a place after a locating word.
_NEEDS_LOCATING = frozenset({"roma", "pest", "anna", "man", "mustang", "split", "nancy"})
# Names that are far more often something else than the place.
_AMBIGUOUS = frozenset({
    "nice", "reading", "mobile", "orange", "jordan", "chad", "georgia", "turkey",
    "victoria", "florence", "charlotte", "phoenix", "austin", "jackson", "lincoln",
    "marion", "marie", "paris hilton", "bath", "derby", "wells", "march", "mark",
    "august", "essen", "halle", "mein", "wald", "hof", "bad", "ebene", "gent",
    "bar", "pau", "ham", "van", "sale", "bury", "hull", "reus", "mars", "lens",
    "dover", "rock", "pasadena", "santa", "san", "villa", "city", "town", "sur",
    "niger", "guinea", "dominica", "samoa", "china town", "sandy", "eden",
})
_COUNTRY_ALIASES = {"US": ["usa", "u.s."], "GB": ["uk", "britain", "england"], "AE": ["uae", "emirates"],
                    "RU": ["russland"], "DE": ["deutschland", "allemagne", "alemania", "germania"],
                    "FR": ["frankreich", "francia"], "ES": ["spanien", "españa", "espagne", "spagna"],
                    "IT": ["italien", "italia", "italie"], "VE": [], "BR": ["brasil", "brasilien", "brésil"]}
# Old-layer entries that are a country, US state or German Land, not a town.
_COARSE_OLD: Optional[frozenset[str]] = None


def _coarse_old() -> frozenset[str]:
    global _COARSE_OLD
    if _COARSE_OLD is None:
        keys = list(GAZETTEER)
        a, b = keys.index("california"), keys.index("scotland")
        c = keys.index("saxony")
        _COARSE_OLD = frozenset(keys[a:b + 1] + keys[c:])
    return _COARSE_OLD


def _load_world() -> dict[str, list[tuple[float, float, str, int, str, str]]]:
    global _WORLD
    if _WORLD is None:
        table: dict[str, list[tuple[float, float, str, int, str, str]]] = {}
        names: dict[str, set[str]] = {}
        try:
            with open(_WORLD_PATH, encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("#"):
                        continue
                    k, disp, lat, lon, pop, kind, cc = line.rstrip("\n").split("\t")
                    table.setdefault(k, []).append((float(lat), float(lon), disp, int(pop), kind, cc))
                    if kind == "n":
                        names.setdefault(cc, set()).add(k)
        except OSError:
            table = {}
        for cc, extra in _COUNTRY_ALIASES.items():
            names.setdefault(cc, set()).update(extra)
        _COUNTRY_NAMES.clear()
        _COUNTRY_NAMES.update(names)
        _WORLD = table
    return _WORLD


def _named_countries(low: str) -> set[str]:
    """Country codes whose name appears in the (lowercased) text."""
    return {cc for cc, ns in _COUNTRY_NAMES.items()
            if any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", low) for n in ns)}


def world_candidates(text: str) -> list[tuple[int, int, float, float, str, int, str]]:
    """All place mentions found in `text` against the world table, as
    (start, n_words, lat, lon, display, pop, kind)."""
    if not text:
        return []
    world = _load_world()
    low = text.lower()
    # "İstanbul'da", "Leeds's": the part before the apostrophe is the name.
    toks = [(m.start(), re.split("['\u2019]", m.group())[0]) for m in _WORD_RE.finditer(text)]
    named: Optional[set[str]] = None
    out = []
    for i in range(len(toks)):
        for n in range(min(_MAX_NGRAM, len(toks) - i), 0, -1):
            words = [t for _, t in toks[i:i + n]]
            key = " ".join(words).lower().replace("\u0307", "")   # Turkish dotted capital I
            cands = world.get(key)
            if cands is None or key in _AMBIGUOUS:
                continue
            prev = toks[i - 1][1].lower() if i else ""
            located = prev in _LOCATING
            weak = prev in _WEAK_LOCATING
            if n == 1:
                w = words[0]
                cased = w.lower() != w.upper()       # False for Arabic, CJK, ...
                if cased and not w[0].isupper():
                    continue
                if cands[0][4] == "n" and cased and not located:
                    continue            # a country in passing ("Angola, Togo") is not where it happened
                if cased and key in _NEEDS_LOCATING and not (located or weak):
                    continue
                if (cands[0][4] == "c" and cased and not located
                        and cands[0][3] < (_MIN_POP_WEAK if weak else _MIN_POP_BARE)):
                    continue
            elif cands[0][4] == "c" and cands[0][3] < _MIN_POP_MULTIWORD and not located:
                continue
            if len(cands) > 1 and cands[0][4] == "c":
                # Same name in several countries (Valencia ES / VE): the text
                # must say which, or one candidate must dwarf the others.
                if named is None:
                    named = _named_countries(low)
                hinted = [c for c in cands if c[5] in named]
                if hinted:
                    pick = hinted[0]
                elif cands[0][3] >= 4 * cands[1][3]:
                    pick = cands[0]
                else:
                    continue
            else:
                pick = cands[0]
            lat, lon, disp, pop, kind, _cc = pick
            out.append((toks[i][0], n, lat, lon, disp, pop, kind))
            break  # longest match at this position wins
    return out


def _best_world(text: str):
    cands = world_candidates(text)
    if not cands:
        return None
    # a city beats a country, then the longer name, then the earlier mention
    return min(cands, key=lambda c: (c[6] == "n", -c[1], c[0]))


def from_world(text: str) -> Optional[tuple[float, float, str]]:
    """Best place in `text` from the worldwide table only."""
    best = _best_world(text)
    return (best[2], best[3], best[4]) if best else None


def from_offline(text: str) -> Optional[tuple[float, float, str]]:
    """Offline geolocation: the hand-kept gazetteer first, but a town found in
    the worldwide table replaces a mere country/state/Land centre from it."""
    old = from_gazetteer(text)
    if old is not None and not _is_coarse(old):
        return old
    best = _best_world(text)
    if best is not None and (old is None or best[6] == "c"):
        return best[2], best[3], best[4]
    return old


def _is_coarse(hit: tuple[float, float, str]) -> bool:
    for key in _coarse_old():
        if GAZETTEER[key][2] == hit[2]:
            return True
    return False


_STRONG_TRIGGER = (r"in der|in|near|at|bei|im|nach|aus|dans|près de|cerca de|vicino a|perto de")
_WEAK_TRIGGER = r"à|en|em|na|no|de|в|во|في"      # also glue a person's name to a verb: "agresión de Juan Pérez"
_CAP = r"[A-ZÀ-ÖØ-Þ][\w\u00C0-\u024F'\-]+"
_PLACE_AFTER = re.compile(
    rf"(?<!\w)(?P<trig>{_STRONG_TRIGGER}|{_WEAK_TRIGGER})\s+(?P<ph>{_CAP}(?:\s+{_CAP}){{0,2}})")
_STRONG_SET = frozenset(_STRONG_TRIGGER.split("|"))

# A word that says "this is a kind of place" (city, street, district ...) in the
# languages we read. Without one, an unknown capitalised name is not sent out:
# it could be a private person ("agresión de Juan Pérez").
_PLACE_TYPE = frozenset("""
city town village district borough county street road avenue square park station
stadt dorf bezirk kreis gemeinde landkreis ortsteil straße strasse platz gasse allee bahnhof
ville commune quartier rue avenue place gare
ciudad pueblo municipio barrio calle avenida plaza estación
cidade bairro rua vila praça estação
città comune frazione via piazza stazione
stad dorp straat wijk gemeente
mahalle köy ilçe şehir
""".split())
_PLACE_PREFIX = frozenset({"bad", "sankt", "st.", "saint", "sainte"})


def _placelike(phrase: str) -> bool:
    low = phrase.lower()
    if low in GAZETTEER or low in _load_world():
        return True
    words = low.split()
    return bool(words and (words[0] in _PLACE_PREFIX or any(w in _PLACE_TYPE for w in words)))


def place_phrase(text: str) -> Optional[str]:
    """A phrase that is safe to send to the online geocoder, or None.

    It must follow a locating word ("attack in ...") AND look like a place:
    it is in our gazetteer/world table, or carries a place-type word (city,
    Stadt, rue, calle ...) or a Bad/Sankt/Saint prefix. Weak triggers
    (de, en, em, à ...) only count for a single word, never for a multi-word
    name, which is how a private person's name would otherwise leave this
    server. Asking Nominatim for the first eight words of a post gave random
    places; asking for any capitalised name would leak people."""
    for m in _PLACE_AFTER.finditer(text or ""):
        phrase = m.group("ph")
        if m.group("trig") not in _STRONG_SET and " " in phrase:
            continue
        if _placelike(phrase):
            return phrase
    return None


def locate(text: str, allow_network: bool = True) -> Optional[tuple[float, float, str]]:
    """
    Best-effort geolocation. Gazetteer first (free, instant); Nominatim only
    if allowed and the gazetteer misses.
    """
    hit = from_offline(text)
    if hit:
        return hit
    if allow_network:
        # Only send a place-like phrase to the geocoder, never the post.
        phrase = place_phrase(text)
        return from_nominatim(phrase) if phrase else None
    return None


if __name__ == "__main__":
    for t in ["Big fire near London Bridge", "Protest in downtown Seattle",
              "flooding reported in Chennai", "nothing here"]:
        print(f"{t!r:40} -> {locate(t, allow_network=False)}")
