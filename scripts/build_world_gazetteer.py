"""
Build backend/data/world_places.tsv from the GeoNames dumps (CC BY 4.0,
https://www.geonames.org/). Offline, run by hand; the output is committed.

  curl -O https://download.geonames.org/export/dump/cities15000.zip   (unzip it)
  curl -O https://download.geonames.org/export/dump/countryInfo.txt
  python scripts/build_world_gazetteer.py cities15000.txt countryInfo.txt

Output columns: key (lowercase) TAB display TAB lat TAB lon TAB population TAB
kind TAB country code. kind is 'c' (city) or 'n' (country). A key shared by
cities of different countries keeps up to three rows (every candidate with at
least 15% of the biggest one's population), so the reader can refuse to guess
between Valencia in Spain and Valencia in Venezuela. Country points are the
population-weighted mean of that country's cities, only a coarse centre.
"""
import sys, re, collections

cities_path, countries_path = sys.argv[1], sys.argv[2]
# letters of any script, including the combining marks Indic and Thai words need
L = r"(?:[^\W\d_]|[\u0300-\u036f\u0900-\u0dff\u0e00-\u0e7f])"
LETTERS = re.compile(rf"^{L}(?:{L}|['\-.])*(?: {L}(?:{L}|['\-.])*)*$", re.UNICODE)
ALT_MIN_POP = 500_000      # alternate-language names only for the big cities
ALT_MULTIWORD_MIN_POP = 1_000_000  # multi-word alternates are mostly transliteration noise

# GeoNames' alternate names include thousands of ASCII transliterations that
# are ordinary words in some language ("Dabei" is a pinyin spelling of Dubai,
# "an man" one of Amman), which pinned German posts to Dubai in testing. So
# alternates are taken only when they contain a non-ASCII letter (Cyrillic,
# Arabic, Devanagari, accented Latin ...), plus this short list of ASCII
# exonyms, spelled the way the language writes them. alias -> GeoNames name.
EXONYMS = {
    "wien": "Vienna", "roma": "Rome", "moskau": "Moscow", "moscou": "Moscow", "moscu": "Moscow",
    "londres": "London", "londra": "London", "parigi": "Paris", "praga": "Prague", "prag": "Prague",
    "lissabon": "Lisbon", "lisboa": "Lisbon", "warschau": "Warsaw", "varsovie": "Warsaw", "varsovia": "Warsaw",
    "mailand": "Milan", "milano": "Milan", "milan": "Milan", "neapel": "Naples", "napoli": "Naples", "naples": "Naples",
    "venedig": "Venice", "venezia": "Venice", "florenz": "Florence", "firenze": "Florence",
    "bruessel": "Brussels", "bruxelles": "Brussels", "bruselas": "Brussels", "kopenhagen": "Copenhagen",
    "athen": "Athens", "athenes": "Athens", "atenas": "Athens", "atene": "Athens", "peking": "Beijing", "pekin": "Beijing",
    "pequim": "Beijing", "tokio": "Tokyo", "kairo": "Cairo", "le caire": "Cairo", "el cairo": "Cairo", "il cairo": "Cairo",
    "bagdad": "Baghdad", "teheran": "Tehran", "teheran": "Tehran", "bombay": "Mumbai", "kalkutta": "Kolkata", "calcutta": "Kolkata",
    "singapur": "Singapore", "genf": "Geneva", "geneve": "Geneva", "ginebra": "Geneva", "zuerich": "Zurich",
    "kiew": "Kyiv", "kiev": "Kyiv", "kyiv": "Kyiv", "bukarest": "Bucharest", "belgrad": "Belgrade", "sofia": "Sofia",
    "budapest": "Budapest", "istanbul": "Istanbul", "estambul": "Istanbul", "constantinopla": "Istanbul",
    "nueva york": "New York City", "nova york": "New York City", "new york": "New York City", "new york city": "New York City",
    "nova iorque": "New York City", "los angeles": "Los Angeles", "san francisco": "San Francisco",
    "mexico": "Mexico City", "ciudad de mexico": "Mexico City", "sao paulo": "Sao Paulo", "rio de janeiro": "Rio de Janeiro",
    "buenos aires": "Buenos Aires", "tel aviv": "Tel Aviv", "jerusalen": "Jerusalem", "damaskus": "Damascus", "damas": "Damascus",
    "mekka": "Mecca", "neu delhi": "New Delhi", "nairobi": "Nairobi", "kapstadt": "Cape Town", "le cap": "Cape Town",
    "ciudad del cabo": "Cape Town", "rangun": "Yangon", "hanoi": "Hanoi", "saigon": "Ho Chi Minh City", "mumbai": "Mumbai",
    "sankt petersburg": "Saint Petersburg", "saint-petersbourg": "Saint Petersburg", "san petersburgo": "Saint Petersburg",
    "colonia": "Cologne", "cologne": "Cologne", "munich": "Munich", "munique": "Munich", "monaco di baviera": "Munich",
    "nuernberg": "Nuremberg", "nuremberg": "Nuremberg", "nuremberga": "Nuremberg", "hanover": "Hanover", "dresde": "Dresden",
    "francfort": "Frankfurt am Main", "frankfurt": "Frankfurt am Main", "francoforte": "Frankfurt am Main",
}
ALT_MIN_LEN = 4

countries, cn_name = {}, {}
for line in open(countries_path, encoding="utf-8"):
    if line.startswith("#") or not line.strip():
        continue
    f = line.rstrip("\n").split("\t")
    cn_name[f[0]] = f[4]

places = {}   # key -> {cc: (pop, display, lat, lon, kind)}
wsum = collections.defaultdict(lambda: [0.0, 0.0, 0.0])

def put(key, pop, disp, lat, lon, kind, cc):
    key = key.strip().lower()
    if len(key) < 3 or not LETTERS.match(key):
        return
    cands = places.setdefault(key, {})
    cur = cands.get(cc)
    if cur is None or pop > cur[0]:
        cands[cc] = (pop, disp, lat, lon, kind)

exonym_targets = collections.defaultdict(list)
for alias, target in EXONYMS.items():
    exonym_targets[target.lower()].append(alias)

for line in open(cities_path, encoding="utf-8"):
    f = line.rstrip("\n").split("\t")
    name, ascii_, alts, lat, lon, cc, pop = f[1], f[2], f[3], float(f[4]), float(f[5]), f[8], int(f[14] or 0)
    disp = f"{name}, {cc}"
    w = wsum[cc]; w[0] += lat * pop; w[1] += lon * pop; w[2] += pop
    put(name, pop, disp, lat, lon, "c", cc)
    put(ascii_, pop, disp, lat, lon, "c", cc)
    if pop >= ALT_MIN_POP:
        for a in alts.split(","):
            if (len(a) >= ALT_MIN_LEN and not a.isascii()
                    and (" " not in a.strip() or pop >= ALT_MULTIWORD_MIN_POP)):
                put(a, pop, disp, lat, lon, "c", cc)
    exo = name.lower()
    if exo in exonym_targets:
        for alias in exonym_targets[exo]:
            put(alias, pop, disp, lat, lon, "c", cc)

for cc, nm in cn_name.items():
    w = wsum.get(cc)
    if w and w[2]:
        # countries outrank every city for their own name
        put(nm, 10**12, nm, w[0] / w[2], w[1] / w[2], "n", cc)

with open("backend/data/world_places.tsv", "w", encoding="utf-8") as out:
    out.write("# GeoNames (CC BY 4.0, geonames.org), cities >= 15000 inhabitants. Generated by scripts/build_world_gazetteer.py\n")
    for k in sorted(places):
        ranked = sorted(places[k].items(), key=lambda kv: -kv[1][0])
        best = ranked[0][1][0]
        for cc, (pop, disp, lat, lon, kind) in ranked[:3]:
            if pop * 100 < best * 15 and kind != "n":
                continue
            out.write(f"{k}\t{disp}\t{lat:.4f}\t{lon:.4f}\t{min(pop, 10**9)}\t{kind}\t{cc}\n")
print(len(places), "keys")
