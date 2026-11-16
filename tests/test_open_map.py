"""
2026-11-15: the public map shows unchecked leads, the collector runs every
minute, and the classifier reads more European languages.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import lawref  # noqa: E402


@pytest.mark.parametrize("text,cat", [
    ("Rasistiskt angrepp mot man i Malmö", "violence"),           # sv
    ("Rasszista támadás Budapesten, megverték", "violence"),      # hu
    ("Ρατσιστική επίθεση σε μετανάστη", "violence"),               # el
    ("Útok neonacistů v Praze, rasistický motiv", "violence"),    # cs
    ("Atac rasist în București", "violence"),                     # ro
    ("Rasistički napad u Zagrebu", "violence"),                   # hr
    ("Hakkors målat på moské, rasistiskt klotter", "banned_symbol"),
    ("Tuhopoltto vastaanottokeskuksessa, rasistinen motiivi", "arson"),  # fi
])
def test_more_european_languages_are_classified(text, cat):
    assert lawref.classify(text)["category"] == cat


@pytest.mark.parametrize("text", [
    "Rasismus ist ein Thema der Woche",         # context word, no incident in a gated language
    "Budapest weather today: sunny",
    "Atacul a fost respins de portar",          # ro football: incident word, no hate context
])
def test_no_context_word_means_no_category(text):
    assert lawref.classify(text)["category"] in ("unclassified", "far_right_mention")


def test_collector_runs_every_minute_by_default():
    if os.environ.get("DXMAP_HEARTBEAT_SECONDS") is None:
        import agent
        assert agent.HEARTBEAT_SECONDS == 60


@pytest.mark.parametrize("raw,out", [
    ("genommen werden@Bundesrat sagt", "genommen werden@… sagt"),
    ("#rechtsextremismus@lagedernation", "#rechtsextremismus@…"),
    ("si=VZ7L3t0@BrittanyPaigesq #nazis", "si=VZ7L3t0@… #nazis"),
    ("pruef-bw@pruef_sl @x", "pruef-bw@… @…"),
    ("x.mp3@abc@mastodon.social y", "x.mp3@… y"),
    ("c@user@ard.social", "c@…"),
    ("am 12.09.@pruef_sn", "am 12.09.@…"),
    ("Video.@pruef_muenchen", "Video.@…"),
    ("mail redaktion@saarnews.com", "mail redaktion@saarnews.com"),
    ("poststelle@sta-frankfurt.justiz.hessen.de", "poststelle@sta-frankfurt.justiz.hessen.de"),
    ("By Shelby Erdman @ Atlanta Black Star.", "By Shelby Erdman @ Atlanta Black Star."),
])
def test_glued_handles_are_removed_but_emails_stay(raw, out):
    import app
    assert app._strip_handles(raw) == out


def test_youtube_key_goes_in_a_header_and_terms_rotate(monkeypatch):
    import asyncio
    import agent

    seen = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"items": [{"id": {"videoId": "v1"}, "snippet": {"title": "a &amp; b", "description": "d"}}]}

    class Client:
        async def get(self, url, params=None, headers=None):
            seen.append((url, dict(params or {}), dict(headers or {})))
            return Resp()

    monkeypatch.setattr(agent, "YOUTUBE_API_KEY", "test-key-123")
    agent.STATE["youtube_next"] = 0
    items = asyncio.run(agent.source_youtube(Client()))
    assert items[0]["title"] == "a & b"
    assert len(seen) == agent.YOUTUBE_QUERIES_PER_RUN
    for url, params, headers in seen:
        assert "test-key-123" not in url and "test-key-123" not in str(params)
        assert headers["X-Goog-Api-Key"] == "test-key-123"
    first = [p["q"] for _, p, _ in seen]
    seen.clear()
    asyncio.run(agent.source_youtube(Client()))
    assert [p["q"] for _, p, _ in seen] != first  # next run, next terms


def test_youtube_runs_at_most_every_30_minutes(monkeypatch):
    import asyncio
    import agent

    calls = []

    async def fake_run(name, adapter, client):
        calls.append(name)
        return []

    monkeypatch.setattr(agent, "run_one_source", fake_run)
    monkeypatch.setattr(agent, "build_sources", lambda: [("bluesky", True, object()), ("youtube", True, object())])
    agent.STATE["source_last_run"] = {}
    asyncio.run(agent.heartbeat_once())
    asyncio.run(agent.heartbeat_once())
    assert calls.count("bluesky") == 2 and calls.count("youtube") == 1
    assert agent.SOURCE_EVERY_S["youtube"] == 1800
