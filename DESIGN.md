---
name: Discrimination Map
description: Worldwide forensic observatory — WELTARCHIV for hate incidents, documenting pattern with archival rigor across all countries
colors:
  paper: "#fdf8f0"
  paper-2: "#f4efe6"
  ocean: "#eef2fb"
  ink: "#0a1629"
  line: "#d6cfbe"
  hair: "#c8c0ad"
  vermillion: "#c13420"
  steel: "#3a6b8c"
  mint: "#1f9b54"
typography:
  display:
    fontFamily: "Sora, General Sans, system-ui, sans-serif"
    fontSize: "clamp(1.4rem, 3.2vw, 2rem)"
    fontWeight: 800
  body:
    fontFamily: "General Sans, system-ui, sans-serif"
    fontSize: "13.5px"
  mono:
    fontFamily: "Fragment Mono, ui-monospace, monospace"
    fontSize: "10px"
---

# Design System: Discrimination Map — World Observatory

## Overview

**Creative North Star: "Weltarchiv — World Observatory & Federal Survey Office"**

Worldwide forensic atlas, not a national ledger. Paper on ink, vermillion forensic tab, ocean blue, ledger hairlines — now spanning all countries. EqualEarth atlas + Orthographic globe toggle, graticule, crosshair pins scaled by zoom. World stats (countries, 24h ticker), geocode flyTo worldwide, top-country chips, richer ledger with NEU badges and nearby context. Updated UX is not simplified — it is more capable, more live, more worldwide.

## Colors

Paper/ink/vermilion core + ocean #eef2fb for world sea. Country fills: Germany #ede7db ink stroke, incident countries #f7ede0, rest paper. Accents remain category-precise, never neon.

## Typography

Sora 800 display, General Sans 500 body, Fragment Mono 10px tabular — worldwide labels stay tabular-nums.

## Layout

Ink world bar (WELTARCHIV • WORLD LEDGER • {n} LÄNDER). Map left 56% + ledger right 44% desktop; stacked 48vh map mobile with tab switch. Map header shows WELT + top countries + WELT reset; ledger has 4-stat strip (WELTBESTAND/NEU/GEPRÜFT/ABDECKUNG), search with geocode dropdown + quick-city pills, collapsible organ-stop cats, ruler, 32px ruled ledger with NEU left rule and country line.

## Elevation & Depth

Paper layers + 1px hairlines, soft ink shadows only for caption/compass/ticker/sheet. Globe uses radial ocean gradient.

## Shapes

Pill stops, 10-14px radii, crosshair markers scaled 1/zoom^0.28, star for solidarity, halo for fuzzed.

## Components

World projection tabs (ATLAS/MERCATOR/GLOBE), zoom +/−/RESET, live ticker (mint pulse), detail sheet with WELT-ORT + nearby 3, worldwide report modal with live stats.

## Do's and Don'ts

- Do keep worldwide scope — stats, geocode, top countries, focus flyTo must work globally, not Germany-only
- Do keep more updated UX: geocode, collapsible filters, nearby, live ticker, globe — not just simplified list
- Don't revert to Germany-only BLATT DE caption or 2400 scale mercator — world is EqualEarth 175 or globe
