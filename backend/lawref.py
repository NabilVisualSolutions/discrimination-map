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
# title_fr/title_ar are translated titles only — the map's statute reference
# is German criminal code, and translating the summary/penalty text itself
# into French/Arabic risks introducing legal-terminology errors without a
# legal translator in the loop. fr/ar readers get a translated title plus
# the English summary/penalty (the de/en pair is the one kept fully native
# in both languages, since German speakers reading about German law is the
# case worth getting exactly right).
STATUTES: dict[str, dict[str, str]] = {
    "StGB-86a": {
        "title_de": "§ 86a StGB — Verwenden von Kennzeichen verfassungswidriger Organisationen",
        "title_en": "§ 86a StGB — Use of symbols of unconstitutional organizations",
        "title_fr": "§ 86a StGB — Utilisation de symboles d'organisations anticonstitutionnelles",
        "title_ar": "المادة 86a من قانون العقوبات — استخدام رموز منظمات مناهضة للدستور",
        "summary": "Public use/distribution of banned symbols: swastika, SS runes, "
                   "the Hitler salute, 'Sieg Heil', Reichskriegsflagge, coded ciphers "
                   "like '88'/'HH'. Outside art, science, research or reporting.",
        "summary_de": "Öffentliches Verwenden/Verbreiten verbotener Symbole: Hakenkreuz, "
                   "SS-Runen, Hitlergruß, „Sieg Heil“, Reichskriegsflagge, Zahlencodes "
                   "wie „88“/„HH“. Ausgenommen Kunst, Wissenschaft, Forschung oder Berichterstattung.",
        "penalty": "Up to 3 years imprisonment or a fine.",
        "penalty_de": "Bis zu 3 Jahre Freiheitsstrafe oder Geldstrafe.",
    },
    "StGB-86": {
        "title_de": "§ 86 StGB — Verbreiten von Propagandamitteln verfassungswidriger Organisationen",
        "title_en": "§ 86 StGB — Dissemination of propaganda of unconstitutional organizations",
        "title_fr": "§ 86 StGB — Diffusion de propagande d'organisations anticonstitutionnelles",
        "title_ar": "المادة 86 من قانون العقوبات — نشر دعاية منظمات مناهضة للدستور",
        "summary": "Producing or distributing propaganda material of banned "
                   "organizations (leaflets, recordings, digital media).",
        "summary_de": "Herstellen oder Verbreiten von Propagandamaterial verbotener "
                   "Organisationen (Flugblätter, Aufnahmen, digitale Medien).",
        "penalty": "Up to 3 years imprisonment or a fine.",
        "penalty_de": "Bis zu 3 Jahre Freiheitsstrafe oder Geldstrafe.",
    },
    "StGB-130": {
        "title_de": "§ 130 StGB — Volksverhetzung",
        "title_en": "§ 130 StGB — Incitement to hatred",
        "title_fr": "§ 130 StGB — Incitation à la haine",
        "title_ar": "المادة 130 من قانون العقوبات — التحريض على الكراهية",
        "summary": "Inciting hatred against a national, racial, religious or ethnic "
                   "group, calling for violence against them, or assaulting their "
                   "human dignity, in a way capable of disturbing the public peace.",
        "summary_de": "Aufstacheln zum Hass gegen eine nationale, rassische, religiöse "
                   "oder ethnische Gruppe, Aufrufen zu Gewalt gegen sie, oder Angriff "
                   "auf ihre Menschenwürde, in einer Weise, die den öffentlichen Frieden stört.",
        "penalty": "3 months to 5 years imprisonment.",
        "penalty_de": "3 Monate bis 5 Jahre Freiheitsstrafe.",
    },
    "StGB-130-3": {
        "title_de": "§ 130 Abs. 3 StGB — Leugnung/Verharmlosung des Holocaust",
        "title_en": "§ 130(3) StGB — Holocaust denial or trivialization",
        "title_fr": "§ 130 al. 3 StGB — Négation ou banalisation de l'Holocauste",
        "title_ar": "المادة 130(3) من قانون العقوبات — إنكار أو تهوين الهولوكوست",
        "summary": "Publicly approving, denying or downplaying the Nazi genocide, "
                   "in a way capable of disturbing the public peace.",
        "summary_de": "Öffentliches Billigen, Leugnen oder Verharmlosen des NS-Völkermords, "
                   "in einer Weise, die den öffentlichen Frieden stört.",
        "penalty": "Up to 5 years imprisonment or a fine.",
        "penalty_de": "Bis zu 5 Jahre Freiheitsstrafe oder Geldstrafe.",
    },
    "StGB-111": {
        "title_de": "§ 111 StGB — Öffentliche Aufforderung zu Straftaten",
        "title_en": "§ 111 StGB — Public incitement to commit offences",
        "title_fr": "§ 111 StGB — Incitation publique à commettre des infractions",
        "title_ar": "المادة 111 من قانون العقوبات — التحريض العلني على ارتكاب جرائم",
        "summary": "Publicly calling on others to commit criminal offences.",
        "summary_de": "Öffentliches Auffordern anderer zur Begehung von Straftaten.",
        "penalty": "As for the offence incited; otherwise up to 5 years or a fine.",
        "penalty_de": "Wie die angestiftete Tat; sonst bis zu 5 Jahre oder Geldstrafe.",
    },
    "StGB-140": {
        "title_de": "§ 140 StGB — Belohnung und Billigung von Straftaten",
        "title_en": "§ 140 StGB — Rewarding or approving of offences",
        "title_fr": "§ 140 StGB — Récompense et approbation d'infractions",
        "title_ar": "المادة 140 من قانون العقوبات — مكافأة الجرائم وإقرارها",
        "summary": "Publicly approving of, or rewarding, serious offences already "
                   "committed (e.g. celebrating a racist attack).",
        "summary_de": "Öffentliches Billigen oder Belohnen bereits begangener schwerer "
                   "Straftaten (z. B. Feiern eines rassistischen Angriffs).",
        "penalty": "Up to 3 years imprisonment or a fine.",
        "penalty_de": "Bis zu 3 Jahre Freiheitsstrafe oder Geldstrafe.",
    },
    "StGB-241": {
        "title_de": "§ 241 StGB — Bedrohung",
        "title_en": "§ 241 StGB — Threatening the commission of an offence",
        "title_fr": "§ 241 StGB — Menace de commettre une infraction",
        "title_ar": "المادة 241 من قانون العقوبات — التهديد بارتكاب جريمة",
        "summary": "Threatening a person with a serious crime against them or someone close.",
        "summary_de": "Bedrohen einer Person mit einem Verbrechen gegen sie oder eine ihr nahestehende Person.",
        "penalty": "Up to 2 years (up to 3 if made publicly) or a fine.",
        "penalty_de": "Bis zu 2 Jahre (bis zu 3 bei öffentlicher Begehung) oder Geldstrafe.",
    },
    "StGB-223-306": {
        "title_de": "§ 223 / § 306 StGB — Körperverletzung / Brandstiftung",
        "title_en": "§ 223 / § 306 StGB — Assault / arson (violent offences)",
        "title_fr": "§ 223 / § 306 StGB — Coups et blessures / incendie volontaire",
        "title_ar": "المادة 223 / 306 من قانون العقوبات — إيذاء جسدي / حرق متعمد",
        "summary": "Physical attacks on persons, or arson against property — the "
                   "'terror' end of far-right activity. Charged as the specific offence.",
        "summary_de": "Körperliche Angriffe auf Personen oder Brandstiftung gegen Eigentum — "
                   "das „Terror“-Ende rechtsextremer Aktivität. Angeklagt als die jeweilige Straftat.",
        "penalty": "Assault: up to 5 years. Arson: 1 to 10+ years depending on severity.",
        "penalty_de": "Körperverletzung: bis zu 5 Jahre. Brandstiftung: 1 bis über 10 Jahre je nach Schwere.",
    },
    "StGB-46-2": {
        "title_de": "§ 46 Abs. 2 StGB — Rassistische/menschenverachtende Beweggründe",
        "title_en": "§ 46(2) StGB — Racist/inhumane motives as aggravating factors",
        "title_fr": "§ 46 al. 2 StGB — Motifs racistes/inhumains comme circonstances aggravantes",
        "title_ar": "المادة 46(2) من قانون العقوبات — دوافع عنصرية/لاإنسانية كعامل مشدِّد",
        "summary": "Not a standalone offence: racist, xenophobic or otherwise "
                   "inhumane motives must aggravate sentencing for the underlying crime.",
        "summary_de": "Kein eigenständiger Straftatbestand: rassistische, fremdenfeindliche "
                   "oder sonst menschenverachtende Beweggründe müssen die Strafzumessung "
                   "der zugrunde liegenden Tat verschärfen.",
        "penalty": "Increases the sentence for the underlying offence.",
        "penalty_de": "Erhöht die Strafe für die zugrunde liegende Tat.",
    },
    "VereinsG-20": {
        "title_de": "§ 20 VereinsG — Zuwiderhandlung gegen ein Vereinsverbot",
        "title_en": "§ 20 Vereinsgesetz — Continuing a banned association",
        "title_fr": "§ 20 VereinsG — Poursuite d'une association interdite",
        "title_ar": "المادة 20 من قانون الجمعيات — الاستمرار في جمعية محظورة",
        "summary": "Continuing, or acting for, an organization banned by the state "
                   "(e.g. maintaining a prohibited neo-Nazi group).",
        "summary_de": "Fortführen einer vom Staat verbotenen Organisation oder Handeln "
                   "für sie (z. B. Aufrechterhalten einer verbotenen Neonazi-Gruppe).",
        "penalty": "Up to 1 year imprisonment or a fine.",
        "penalty_de": "Bis zu 1 Jahr Freiheitsstrafe oder Geldstrafe.",
    },
}

# Display metadata for every category `classify()` can return — label + a
# distinct color for the map/legend, ordered by severity (matches
# _INDICATORS below). None of these are sensitive-personal-data categories
# (no "sexual assault" bucket exists in this Germany-only, statute-based
# build), so coloring by category carries none of the location-fuzzing /
# moderation-queue requirements the not-yet-built global expansion has.
CATEGORIES: dict[str, dict[str, str]] = {
    # Colors tuned for legibility on the map's light background — the map
    # was dark when these were first picked (see git history for the
    # original, brighter values if ever reverting to a dark theme).
    "arson":              {"label": "Arson / firebombing", "color": "#E0433A"},
    "violence":           {"label": "Physical attack", "color": "#E06A1F"},
    "threat":             {"label": "Threat against persons", "color": "#C99400"},
    "banned_symbol":      {"label": "Banned symbol / salute", "color": "#8E4FD6"},
    "holocaust_denial":   {"label": "Holocaust denial", "color": "#C94A75"},
    "incitement":         {"label": "Incitement to hatred", "color": "#1F72D6"},
    "propaganda":         {"label": "Banned propaganda", "color": "#1F9B54"},
    "banned_org":         {"label": "Banned organization activity", "color": "#0EA695"},
    "assembly":           {"label": "Far-right assembly / march", "color": "#5B6B85"},
    "far_right_mention":  {"label": "Far-right context (needs review)", "color": "#495467"},

    # Broader, global taxonomy — not tied to a specific statute, colors kept
    # identical to outreach/landing-page.html's chipcloud and
    # frontend/preview-light.html for consistency across the whole project.
    "racism":                 {"label": "Racism", "color": "#FF5C5C"},
    "islamophobia":           {"label": "Islamophobia", "color": "#FFA94D"},
    "antisemitism":           {"label": "Antisemitism", "color": "#4DA6FF"},
    "homophobia_transphobia": {"label": "Homophobia / transphobia", "color": "#B983FF"},
    "neo_nazi":               {"label": "Neo-Nazi activity / signs", "color": "#C99400"},
    "xenophobia":             {"label": "Xenophobia", "color": "#4CD97B"},
    "sexual_violence":        {"label": "Sexual violence", "color": "#2BD9C9"},
    "harassment":             {"label": "Harassment", "color": "#E8779E"},
    "other":                  {"label": "Other", "color": "#8891A8"},
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
