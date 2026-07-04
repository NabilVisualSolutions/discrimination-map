"""
German-law reference + a lightweight signal detector for the Germany-focused
far-right monitoring build.

IMPORTANT — accuracy & fairness:
  This module NEVER concludes that a person "is a Neo-Nazi" or "is guilty".
  It detects textual *indicators* (e.g. a banned symbol is named, an incitement
  phrase appears) and maps them to a POSSIBLY-APPLICABLE statute. Everything it
  produces is an automated, unverified signal for a human to review. Under German
  law, falsely accusing someone is itself an offence (§186/§187 StGB), so the
  whole pipeline is built around "alleged / reported + evidence", not verdicts.

Statute numbers verified against the Strafgesetzbuch (StGB).
"""
from __future__ import annotations

import re
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# Statute reference. Codes are the keys the rest of the app stores/looks up.   #
# --------------------------------------------------------------------------- #
STATUTES: dict[str, dict[str, str]] = {
    "StGB-86a": {
        "title_de": "§ 86a StGB — Verwenden von Kennzeichen verfassungswidriger Organisationen",
        "title_en": "§ 86a StGB — Use of symbols of unconstitutional organizations",
        "summary": "Public use/distribution of banned symbols: swastika, SS runes, "
                   "the Hitler salute, 'Sieg Heil', Reichskriegsflagge, coded ciphers "
                   "like '88'/'HH'. Outside art, science, research or reporting.",
        "penalty": "Up to 3 years imprisonment or a fine.",
    },
    "StGB-86": {
        "title_de": "§ 86 StGB — Verbreiten von Propagandamitteln verfassungswidriger Organisationen",
        "title_en": "§ 86 StGB — Dissemination of propaganda of unconstitutional organizations",
        "summary": "Producing or distributing propaganda material of banned "
                   "organizations (leaflets, recordings, digital media).",
        "penalty": "Up to 3 years imprisonment or a fine.",
    },
    "StGB-130": {
        "title_de": "§ 130 StGB — Volksverhetzung",
        "title_en": "§ 130 StGB — Incitement to hatred",
        "summary": "Inciting hatred against a national, racial, religious or ethnic "
                   "group, calling for violence against them, or assaulting their "
                   "human dignity, in a way capable of disturbing the public peace.",
        "penalty": "3 months to 5 years imprisonment.",
    },
    "StGB-130-3": {
        "title_de": "§ 130 Abs. 3 StGB — Leugnung/Verharmlosung des Holocaust",
        "title_en": "§ 130(3) StGB — Holocaust denial or trivialization",
        "summary": "Publicly approving, denying or downplaying the Nazi genocide, "
                   "in a way capable of disturbing the public peace.",
        "penalty": "Up to 5 years imprisonment or a fine.",
    },
    "StGB-111": {
        "title_de": "§ 111 StGB — Öffentliche Aufforderung zu Straftaten",
        "title_en": "§ 111 StGB — Public incitement to commit offences",
        "summary": "Publicly calling on others to commit criminal offences.",
        "penalty": "As for the offence incited; otherwise up to 5 years or a fine.",
    },
    "StGB-140": {
        "title_de": "§ 140 StGB — Belohnung und Billigung von Straftaten",
        "title_en": "§ 140 StGB — Rewarding or approving of offences",
        "summary": "Publicly approving of, or rewarding, serious offences already "
                   "committed (e.g. celebrating a racist attack).",
        "penalty": "Up to 3 years imprisonment or a fine.",
    },
    "StGB-241": {
        "title_de": "§ 241 StGB — Bedrohung",
        "title_en": "§ 241 StGB — Threatening the commission of an offence",
        "summary": "Threatening a person with a serious crime against them or someone close.",
        "penalty": "Up to 2 years (up to 3 if made publicly) or a fine.",
    },
    "StGB-223-306": {
        "title_de": "§ 223 / § 306 StGB — Körperverletzung / Brandstiftung",
        "title_en": "§ 223 / § 306 StGB — Assault / arson (violent offences)",
        "summary": "Physical attacks on persons, or arson against property — the "
                   "'terror' end of far-right activity. Charged as the specific offence.",
        "penalty": "Assault: up to 5 years. Arson: 1 to 10+ years depending on severity.",
    },
    "StGB-46-2": {
        "title_de": "§ 46 Abs. 2 StGB — Rassistische/menschenverachtende Beweggründe",
        "title_en": "§ 46(2) StGB — Racist/inhumane motives as aggravating factors",
        "summary": "Not a standalone offence: racist, xenophobic or otherwise "
                   "inhumane motives must aggravate sentencing for the underlying crime.",
        "penalty": "Increases the sentence for the underlying offence.",
    },
    "VereinsG-20": {
        "title_de": "§ 20 VereinsG — Zuwiderhandlung gegen ein Vereinsverbot",
        "title_en": "§ 20 Vereinsgesetz — Continuing a banned association",
        "summary": "Continuing, or acting for, an organization banned by the state "
                   "(e.g. maintaining a prohibited neo-Nazi group).",
        "penalty": "Up to 1 year imprisonment or a fine.",
    },
}

# Category label -> which statute it points at, plus a human "reason" phrase.
# Ordered by severity so the most serious matched signal wins.
_INDICATORS: list[tuple[str, str, str, str]] = [
    # (regex, category, statute_code, reason phrase)
    (r"\b(brandanschlag|brandstiftung|arson|firebomb|molotov)\b",
     "arson", "StGB-223-306", "arson / firebombing reported"),
    (r"\b(angriff|überfall|ueberfall|attack|assault|zusammengeschlagen|niedergestochen|stabbing)\b",
     "violence", "StGB-223-306", "physical attack reported"),
    (r"\b(morddrohung|todesdrohung|death threat|drohung|threat|wir kriegen euch)\b",
     "threat", "StGB-241", "threat against persons"),
    (r"(hakenkreuz|swastika|hitlergru|hitler salute|sieg heil|ss-rune|reichskriegsflagg|hakenkreuze)",
     "banned_symbol", "StGB-86a", "banned symbol / salute displayed"),
    (r"\b(holocaust ?leugnung|auschwitzlüge|auschwitzluege|holocaust denial|shoah denial)\b",
     "holocaust_denial", "StGB-130-3", "Holocaust denial / trivialization"),
    (r"\b(volksverhetzung|hetze|incitement|ausländer raus|auslaender raus|rassistische parole)\b",
     "incitement", "StGB-130", "incitement to hatred"),
    (r"\b(propagandamittel|nazi-?propaganda|nazipropaganda|propaganda material)\b",
     "propaganda", "StGB-86", "distribution of banned propaganda"),
    (r"\b(verbotene? organisation|vereinsverbot|banned (group|organi[sz]ation))\b",
     "banned_org", "VereinsG-20", "activity of a banned organization"),
    (r"\b(aufmarsch|naziaufmarsch|kundgebung|rechte demo|neonazi-?demo|far-?right (march|rally))\b",
     "assembly", None, "far-right assembly / march (monitoring)"),  # not itself a crime
]

_COMPILED = [(re.compile(rx, re.IGNORECASE), cat, code, reason)
             for rx, cat, code, reason in _INDICATORS]

# Broad far-right relevance gate (German + English), so we don't classify
# unrelated posts. Kept deliberately about the movement, not about slurs.
_RELEVANCE = re.compile(
    r"\b(neonazi|neo-?nazi|nazi|rechtsextrem|rechtsextremismus|rechtsradikal|"
    r"faschis|fascist|far-?right|npd|der iii\.? weg|die rechte|hammerskin|"
    r"combat 18|blood ?& ?honour|identitär|identitaer|reichsbürger|reichsbuerger|"
    r"hooligan|afd-?nähe|völkisch|voelkisch|white supremac|rechte gewalt|hate crime)\b",
    re.IGNORECASE)


def classify(text: str) -> dict[str, Any]:
    """
    Inspect text for far-right indicators.

    Returns a dict:
      relevant   : bool  — did it trip the far-right relevance gate or a signal?
      category   : str   — the strongest matched category, or 'unclassified'
      law_code   : str|None — a POSSIBLY-applicable statute key in STATUTES
      reason     : str   — human-readable reason phrase (automated signal)
      indicators : list[str] — all matched category labels
    """
    text = text or ""
    matched: list[tuple[str, Optional[str], str]] = []
    for rx, cat, code, reason in _COMPILED:
        if rx.search(text):
            matched.append((cat, code, reason))

    relevant = bool(matched) or bool(_RELEVANCE.search(text))
    if matched:
        # First match wins (list is ordered most-severe first).
        cat, code, reason = matched[0]
        return {
            "relevant": relevant, "category": cat, "law_code": code,
            "reason": f"Automated signal: {reason}",
            "indicators": [m[0] for m in matched],
        }
    if relevant:
        return {
            "relevant": True, "category": "far_right_mention", "law_code": None,
            "reason": "Automated signal: far-right context mentioned (needs review)",
            "indicators": [],
        }
    return {"relevant": False, "category": "unclassified", "law_code": None,
            "reason": "", "indicators": []}


def law_brief(code: Optional[str]) -> Optional[dict[str, str]]:
    """Look up a statute for display. Returns None for an unknown/empty code."""
    return STATUTES.get(code) if code else None


if __name__ == "__main__":
    for t in [
        "Neonazis zeigen Hakenkreuz und rufen Sieg Heil bei Aufmarsch in Dortmund",
        "Brandanschlag auf Geflüchtetenunterkunft in Sachsen – rechtsextremer Hintergrund",
        "Just a normal post about football in Berlin",
        "Rechte Hetze gegen Geflüchtete auf Marktplatz",
    ]:
        print(f"{t[:55]:55} -> {classify(t)['category']:16} {classify(t)['law_code']}")
