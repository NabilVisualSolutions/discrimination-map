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
