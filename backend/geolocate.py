"""
Turn free text into coordinates.

Two-stage, cheapest first:
  1. Offline gazetteer of major world cities  -> instant, no network.
  2. OSM Nominatim geocoding (free)           -> for anything the gazetteer
     misses. Rate-limited to <=1 req/s per Nominatim's usage policy, with a
     descriptive User-Agent as they require.

If neither resolves, we return None and the report is stored unlocated.
"""
from __future__ import annotations

import os
import re
import time
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
_UA = "DxMap/1.0 (far-right monitoring prototype; contact: admin@example.com)"
_last_nominatim_call = 0.0

# Restrict runtime geocoding to Germany so stray place names elsewhere don't
# pull marks off-focus. Set DXMAP_GEO_COUNTRY="" to disable the restriction.
_GEO_COUNTRY = os.environ.get("DXMAP_GEO_COUNTRY", "de").strip()


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


def from_nominatim(text: str, timeout: float = 8.0) -> Optional[tuple[float, float, str]]:
    """
    Geocode a free-text place via Nominatim. Respects the 1 req/s policy by
    sleeping if we were called too recently. Returns None on any failure.
    """
    global _last_nominatim_call
    if not text or len(text.strip()) < 3:
        return None
    elapsed = time.time() - _last_nominatim_call
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
    try:
        params = {"q": text, "format": "json", "limit": 1}
        if _GEO_COUNTRY:
            params["countrycodes"] = _GEO_COUNTRY
        resp = httpx.get(
            _NOMINATIM,
            params=params,
            headers={"User-Agent": _UA},
            timeout=timeout,
        )
        _last_nominatim_call = time.time()
        resp.raise_for_status()
        data = resp.json()
        if data:
            hit = data[0]
            return float(hit["lat"]), float(hit["lon"]), hit.get("display_name", text)
    except Exception:
        # Network hiccup / rate limit / bad response -> caller stores unlocated.
        return None
    return None


def locate(text: str, allow_network: bool = True) -> Optional[tuple[float, float, str]]:
    """
    Best-effort geolocation. Gazetteer first (free, instant); Nominatim only
    if allowed and the gazetteer misses.
    """
    hit = from_gazetteer(text)
    if hit:
        return hit
    if allow_network:
        # Only send a short, place-like snippet to the geocoder.
        snippet = " ".join(text.split()[:8])
        return from_nominatim(snippet)
    return None


if __name__ == "__main__":
    for t in ["Big fire near London Bridge", "Protest in downtown Seattle",
              "flooding reported in Chennai", "nothing here"]:
        print(f"{t!r:40} -> {locate(t, allow_network=False)}")
