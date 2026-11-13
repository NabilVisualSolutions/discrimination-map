"""Worldwide coverage: offline world gazetteer, multilingual classification,
Mastodon plan, GDELT pacing, Nominatim manners. No network anywhere."""
import asyncio
import os
import sys
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)
os.environ["DXMAP_AGENT"] = "off"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import httpx  # noqa: E402
import pytest  # noqa: E402

import agent  # noqa: E402
import db  # noqa: E402
import geolocate  # noqa: E402
import lawref  # noqa: E402

db.init_db()


# ---- offline world gazetteer ------------------------------------------------

@pytest.mark.parametrize("text,country", [
    ("Racist attack on a mosque in Leeds last night", "GB"),
    ("Racist attack outside a bar in Lagos", "NG"),
    ("Attaque raciste à Marseille", "FR"),
    ("Ataque racista en Bogotá contra migrantes venezolanos", "CO"),
    ("Aggressione razzista a Napoli", "IT"),
    ("Racist abuse of a footballer in Nairobi", "KE"),
    ("حادث عنصري في القاهرة", "EG"),
    ("Anti-Asian assault reported in Sydney", "AU"),
    ("Hate crime in Johannesburg", "ZA"),
    ("Moschee in Köln angegriffen", "DE"),
    ("Hindu temple vandalised in Brisbane", "AU"),
])
def test_world_gazetteer_resolves_cities_in_many_languages(text, country):
    hit = geolocate.from_offline(text)
    assert hit is not None, text
    assert hit[2].endswith(country) or hit[2].endswith({"GB": "UK"}.get(country, country)), hit


def test_ordinary_words_are_not_towns():
    for t in ["It was nice and reading was fun", "a mobile phone and an orange", "Chad and Jordan went home",
              "no place here at all", "Georgia on my mind"]:
        assert geolocate.from_offline(t) is None, t


def test_city_beats_country_and_old_layer_still_wins_for_towns():
    assert geolocate.from_offline("Racist attack in Lagos, Nigeria")[2].startswith("Lagos")
    assert geolocate.from_offline("Neonazis marschieren in Freital")[2] == "Freital, DE"     # old layer, unchanged
    # a Land/country centre from the old layer is replaced by a real town
    assert geolocate.from_offline("Sachsen: Angriff in Leipzig")[2].startswith("Leipzig")
    # ...but stays when nothing better is named
    assert geolocate.from_offline("Angriff in Sachsen")[2] == "Sachsen, DE"


def test_gazetteer_lookup_is_fast():
    import time
    geolocate.from_offline("warm up")
    t = time.time()
    for _ in range(200):
        geolocate.from_offline("A long post about an attack on a mosque somewhere near a small village " * 5)
    assert time.time() - t < 2


def test_place_phrase_for_the_online_geocoder():
    assert geolocate.place_phrase("Racist attack in Bad Freienwalde on Monday") == "Bad Freienwalde"
    assert geolocate.place_phrase("Neonazis zeigen Hakenkreuz und rufen Sieg Heil") is None
    assert geolocate.place_phrase("agression à Villeurbanne hier") == "Villeurbanne"


# ---- Nominatim manners --------------------------------------------------------

def test_nominatim_identifies_itself_caches_and_spaces_requests(monkeypatch):
    calls, sleeps = [], []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((params["q"], headers["User-Agent"]))
        return httpx.Response(200, json=[{"lat": "1.23456", "lon": "2.34567", "display_name": "Somewhere"}],
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(geolocate.httpx, "get", fake_get)
    monkeypatch.setattr(geolocate.time, "sleep", lambda s: sleeps.append(s))
    geolocate._NOMINATIM_CACHE.clear()
    geolocate._last_nominatim_call = 0.0
    a = geolocate.from_nominatim("Smalltown")
    b = geolocate.from_nominatim("smalltown ")           # same place: served from the cache
    c = geolocate.from_nominatim("Othertown")            # new place right after: must wait
    assert a == b and a[:2] == (1.23, 2.35)               # coarsened to ~1 km as before
    assert [q for q, _ in calls] == ["Smalltown", "Othertown"]
    assert all(ua.startswith("dxmap-agent (+https://map.nabilvs.com)") and "example.com" not in ua for _, ua in calls)
    assert sleeps and max(sleeps) <= 1.1 and max(sleeps) > 0.5
    assert c is not None


def test_nominatim_failure_is_not_cached(monkeypatch):
    n = []

    def boom(*a, **k):
        n.append(1)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(geolocate.httpx, "get", boom)
    monkeypatch.setattr(geolocate.time, "sleep", lambda s: None)
    geolocate._NOMINATIM_CACHE.clear()
    assert geolocate.from_nominatim("Faraway") is None
    assert geolocate.from_nominatim("Faraway") is None
    assert len(n) == 2


def test_geocode_pending_sends_a_place_phrase_not_the_post(monkeypatch):
    asked = []
    monkeypatch.setattr(geolocate, "from_nominatim", lambda q, **k: asked.append(q) or None)
    rid = db.insert_report(source="bluesky", external_id="gp1", title="x", url="https://b.example/gp1", status="unverified")
    n = agent._geocode_pending([(rid, "Neonazis zeigen Hakenkreuz und rufen laut Sieg Heil"),
                                (rid, "Racist attack in Bad Freienwalde yesterday")], budget=5)
    assert asked == ["Bad Freienwalde"] and n == 0              # first has no place phrase: no request at all


# ---- multilingual classification ----------------------------------------------

@pytest.mark.parametrize("text", [
    "Attaque raciste à Lyon : un homme agressé par des militants d'extrême droite",
    "Ataque racista contra migrantes en Madrid",
    "Ataque neonazista em São Paulo deixa feridos",
    "Aggressione razzista a Roma, indaga la polizia",
    "Racistische aanval op moskee in Rotterdam",
    "Irkçı saldırı: İstanbul'da mülteci dövüldü",
    "Расистское нападение на мигрантов в Москве",
    "اعتداء عنصري على مسجد في لندن",
    "Atak rasistowski w Warszawie",
    "Nazi-Hakenkreuz an Synagoge gesprüht",
    "Brandanschlag auf Moschee in Köln",
])
def test_classify_accepts_hate_incidents_in_many_languages(text):
    v = lawref.classify(text)
    assert v["relevant"], text
    assert v["category"] in lawref.CATEGORIES


@pytest.mark.parametrize("text", [
    "Football: attaque en première mi-temps pour le PSG",
    "El racismo es un problema social (opinión)",          # context word alone is not an incident
    "Hoy ataque de risa en la oficina",
    "Il gatto ha un attacco di fame",
    "Новая модель телефона вышла в продажу",
])
def test_classify_rejects_unrelated_text_in_other_languages(text):
    assert not lawref.classify(text)["relevant"], text


def test_search_terms_cover_many_languages_and_keep_the_env_override(monkeypatch):
    joined = " ".join(agent.SEARCH_TERMS)
    for needle in ["attaque raciste", "ataque racista", "ırkçı saldırı", "расистское", "اعتداء عنصري", "Neonazi", "racist attack"]:
        assert needle in joined
    assert len(agent.SEARCH_TERMS) >= 50
    import importlib
    monkeypatch.setenv("DXMAP_TERMS", "foo,bar")
    importlib.reload(agent)
    assert agent.SEARCH_TERMS == ["foo", "bar"]
    monkeypatch.delenv("DXMAP_TERMS")
    importlib.reload(agent)


# ---- Mastodon -----------------------------------------------------------------

def test_mastodon_plan_is_global_and_not_a_blind_cross_product():
    insts = {i for i, _ in agent.MASTODON_JOBS}
    assert {"mastodon.social", "norden.social", "nrw.social", "mamot.fr", "masto.es", "mastodon.com.br"} <= insts
    assert not ({"mstdn.social", "sueden.social", "troet.cafe", "chaos.social", "mastodon.cloud"} & insts)   # dead / login-walled
    assert len(agent.MASTODON_JOBS) < 60
    assert ("mamot.fr", "racisme") in agent.MASTODON_JOBS and ("mamot.fr", "Rechtsextremismus") not in agent.MASTODON_JOBS


def test_mastodon_env_override_restores_cross_product(monkeypatch):
    import importlib
    monkeypatch.setenv("DXMAP_MASTODON_INSTANCES", "a.example,b.example")
    monkeypatch.setenv("DXMAP_MASTODON_TAGS", "t1,t2")
    importlib.reload(agent)
    assert agent.MASTODON_JOBS == [("a.example", "t1"), ("a.example", "t2"), ("b.example", "t1"), ("b.example", "t2")]
    monkeypatch.undo()
    importlib.reload(agent)


# ---- GDELT --------------------------------------------------------------------

def test_gdelt_queries_are_worldwide_and_paced(monkeypatch):
    qs = " ".join(agent.GDELT_QUERIES)
    assert "Germany" not in qs and "sourcecountry:germany" not in qs.lower()
    for lang in ["french", "spanish", "portuguese", "turkish", "russian", "arabic", "german", "english"]:
        assert f"sourcelang:{lang}" in qs
    sleeps, seen = [], []
    monkeypatch.setattr(agent, "GDELT_SPACING_S", 6.0)
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(agent.asyncio, "sleep", fake_sleep)

    def handler(req):
        seen.append(req.url.params["query"])
        return httpx.Response(200, json={"articles": [{"url": "https://n.example/" + str(len(seen)), "title": "Racist attack in Leeds",
                                                         "domain": "n.example", "seendate": "20261021T100000Z"}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            agent._gdelt_cursor = 0
            a = await agent.source_gdelt_news(c)
            b = await agent.source_gdelt_news(c)
            return a, b

    a, b = asyncio.run(go())
    assert len(seen) == 2 * agent.GDELT_PER_BEAT
    assert len(set(seen)) == len(seen)                                  # second beat continues where the first stopped
    assert sleeps == [6.0] * (2 * (agent.GDELT_PER_BEAT - 1))           # spaced, never back to back
    assert a[0]["external_id"].startswith("gdelt_") and a[0]["external_id"] == agent._stable_id("gdelt", "https://n.example/1")


def test_gdelt_stops_at_429(monkeypatch):
    seen = []

    async def fake_sleep(s):
        pass

    monkeypatch.setattr(agent.asyncio, "sleep", fake_sleep)

    def handler(req):
        seen.append(1)
        return httpx.Response(429, text="Please limit requests to one every 5 seconds")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await agent.source_gdelt_news(c)

    assert asyncio.run(go()) == [] and len(seen) == 1


def test_stable_id_is_deterministic():
    assert agent._stable_id("gdelt", "https://a.example/x") == agent._stable_id("gdelt", "https://a.example/x")
    assert agent._stable_id("gdelt", "https://a.example/x") != agent._stable_id("gdelt", "https://a.example/y")


def test_agent_stores_a_world_item_with_coordinates():
    item = {"external_id": "w1", "title": "Racist attack on a mosque in Leeds", "body": "", "url": "https://w.example/1", "category": "x"}
    stored, pending = agent._store_item_ex("news", item)
    assert stored and pending is None
    with db._conn() as c:
        r = c.execute("SELECT * FROM reports WHERE external_id='w1'").fetchone()
    assert r["located"] == 1 and "Leeds" in r["place"] and r["status"] == "unverified" and r["human_verified"] == 0


# ---- false positives found by running the gazetteer over real posts -------------------

def test_names_shared_by_two_countries_need_a_hint():
    assert geolocate.from_offline("Racist attack in Valencia last night") is None             # Spain or Venezuela?
    assert geolocate.from_offline("Racist attack in Valencia, Spain")[2] == "Valencia, ES"
    assert geolocate.from_offline("Ataque racista en Valencia, Venezuela")[2] == "Valencia, VE"


@pytest.mark.parametrize("text", [
    "Dabei wurde ein Mann verletzt",                              # not Dubai
    "Man kann das nicht ignorieren",                              # not Man, Cote d'Ivoire
    "Das Ende der Veranstaltung am Mitte der Woche",              # not Ende / Mitte
    "Zentralrat der Sinti und Roma zeigt Anzeige",                # people, not Rome
    "Geflüchtete aus der DR Kongo, Angola, Togo und dem Libanon", # countries in passing
    "an. Man erkennt ihn an seinen Taten",                        # not Amman
])
def test_german_prose_does_not_pin_to_random_places(text):
    assert geolocate.from_offline(text) is None, text


def test_exonyms_and_scripts_resolve():
    assert geolocate.from_offline("Naziaufmarsch in Wien")[2].startswith("Vienna")
    assert geolocate.from_offline("Aggressione neofascista a Roma")[2].startswith("Rome")
    assert geolocate.from_offline("İstanbul'da ırkçı saldırı")[2].startswith("Istanbul")
    assert geolocate.from_offline("नस्लीय हमला: दिल्ली में अफ्रीकी छात्र पर हमला") is not None


PERSON_TEXTS = [
    "Agresión racista de Juan Pérez contra un vecino",                    # es
    "Agresión en Juan Pérez García hace dos días",
    "Agressão de João Silva Santos a um colega",                          # pt
    "Ataque racista em João Silva Santos, dizem testemunhas",
    "Agression raciste de Jean Dupont sur un voisin",                      # fr
    "Agression à Jean Dupont signalée hier",
    "Racist abuse by Michael Johnson at a bus stop",                       # en
    "Attack in Michael Johnson's garden, police say",
    "Angriff durch Hans Müller auf einen Nachbarn",                        # de
    "Übergriff bei Hans Müller zu Hause",
    "Racist attack near Sarah Connor Williams last week",
]


@pytest.mark.parametrize("text", PERSON_TEXTS)
def test_person_names_never_produce_an_outbound_geocode_query(monkeypatch, text):
    asked = []
    monkeypatch.setattr(geolocate.httpx, "get", lambda *a, **k: asked.append(a) or None)
    assert geolocate.place_phrase(text) is None
    geolocate.locate(text, allow_network=True)
    assert asked == []


def test_place_type_cues_and_table_hits_are_sent():
    assert geolocate.place_phrase("Angriff in Musterhausen Bahnhof") == "Musterhausen Bahnhof"
    assert geolocate.place_phrase("racist attack in Elm Street") == "Elm Street"
    assert geolocate.place_phrase("agresión en Calle Mayor") is None            # weak trigger + multi-word
    assert geolocate.place_phrase("agression à Villeurbanne") == "Villeurbanne"  # world table
    assert geolocate.place_phrase("attack in Smalltown yesterday") is None       # unknown name, no cue


def test_offline_results_are_coarsened_before_they_are_stored():
    item = {"external_id": "c1", "title": "Racist attack on a mosque in Leeds", "body": "", "url": "https://w.example/c1"}
    agent._store_item_ex("news", item)
    with db._conn() as c:
        r = c.execute("SELECT lat, lon FROM reports WHERE external_id='c1'").fetchone()
    assert (r["lat"], r["lon"]) == (round(r["lat"], 2), round(r["lon"], 2))
    assert (r["lat"], r["lon"]) == geolocate.coarsen(*geolocate.from_offline(item["title"])[:2])


def test_nominatim_search_is_shared_and_bounded(monkeypatch):
    import threading
    geolocate._NOMINATIM_CACHE.clear()
    monkeypatch.setattr(geolocate.time, "sleep", lambda s: None)
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow_get(url, params=None, headers=None, timeout=None):
        calls.append(params["q"])
        started.set()
        release.wait(5)
        return httpx.Response(200, json=[{"lat": "1", "lon": "2", "display_name": "x"}], request=httpx.Request("GET", url))

    monkeypatch.setattr(geolocate.httpx, "get", slow_get)
    monkeypatch.setattr(geolocate, "_MAX_WAITERS", 2)
    results, busy = [], []

    def worker(q):
        try:
            results.append(geolocate.nominatim_search(q, 5, "en"))
        except geolocate.NominatimBusy:
            busy.append(q)

    ts = [threading.Thread(target=worker, args=(f"place {i}",)) for i in range(5)]
    ts[0].start(); started.wait(2)
    for t in ts[1:]:
        t.start()
    import time as _t
    _t.sleep(0.3)
    release.set()
    for t in ts:
        t.join(5)
    assert len(busy) == 3 and len(results) == 2       # one in flight + one queued; the rest were refused at once
    assert len(calls) == 2


def test_api_geocode_goes_through_the_shared_nominatim_call(monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_module
    import security
    security.limiter.reset()
    app_module._GEOCODE_CACHE.clear()
    geolocate._NOMINATIM_CACHE.clear()
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append((params["q"], params["limit"], headers["User-Agent"]))
        return httpx.Response(200, json=[{"lat": "52.5", "lon": "13.4", "display_name": "Berlin"}],
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(geolocate.httpx, "get", fake_get)
    monkeypatch.setattr(geolocate.time, "sleep", lambda s: None)
    c = TestClient(app_module.app)
    h = {"X-Forwarded-For": "162.158.1.10", "CF-Connecting-IP": "203.0.113.77"}
    r = c.get("/api/geocode?q=Berlin+Mitte", headers=h)
    assert r.status_code == 200 and r.json()["results"][0]["label"] == "Berlin"
    assert seen == [("Berlin Mitte", 5, geolocate._UA)]
    # a different spelling of the same query is served by the shared cache: no second upstream call
    app_module._GEOCODE_CACHE.clear()
    c.get("/api/geocode?q=berlin++mitte", headers=h)
    assert len(seen) == 1
    # saturated queue: fast 503, not a hung worker
    monkeypatch.setattr(geolocate, "_waiting", geolocate._MAX_WAITERS)
    assert c.get("/api/geocode?q=Hamburg+Altona", headers=h).status_code == 503
