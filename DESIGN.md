---
name: Discrimination Map
description: Signal Atlas — chromatic worldwide forensic ledger, high-clarity, high-saturation, fluid to any device
colors:
  paper: "#fffef8"
  paper-2: "#fdf6e3"
  ink: "#0a0f1f"
  line: "#e6dcc2"
  hair: "#d4c9a8"
  vermillion: "#e11d2d"
  steel: "#0284c7"
  mint: "#059669"
  amber: "#d97706"
  violet: "#7c3aed"
typography:
  display:
    fontFamily: "Sora, General Sans, system-ui, sans-serif"
    fontSize: "clamp(1.6rem, 4vw, 2.4rem)"
    fontWeight: 800
  body:
    fontFamily: "General Sans, system-ui, sans-serif"
    fontSize: "clamp(13px, 1.6vw, 15px)"
  mono:
    fontFamily: "Fragment Mono, ui-monospace, monospace"
    fontSize: "11px"
---

# Design System: Discrimination Map — Signal Atlas

## Overview

**Creative North Star: "Signal Atlas — Chromatic Forensic Observatory"**

Surprise: not muted archive but daylight signal atlas — same forensic rigor, now high-clarity, high-saturation. Paper is brighter (#fffef8), ink is deeper (#0a0f1f 16:1), vermillion is pure signal red (#e11d2d), category hues are chromatic not desaturated. Every device reads as one fluid instrument: map and ledger flow into each other via container queries, not breakpoints alone. Clarity comes from 4.5:1 text, 3:1 large, tabular mono, and 8px hairlines that stay crisp at any zoom. Saturation is semantic — red for live/neu, steel for trust, mint for verified — never decoration.

Key: fluid grid, saturated signals, daylight clarity, react-simple-maps globe/atlas inline, Discrimination Map name kept.

## Colors

High saturation, high clarity: paper #fffef8 warm daylight, ink #0a0f1f, vermillion #e11d2d (live), steel #0284c7 (links), mint #059669 (verified), amber #d97706 (fuzzed). Category colors via lawref.py but pushed 12% more chroma via filter saturate(1.12).

## Typography

Sora 800 display at clamp 1.6-2.4rem, General Sans 600 body at clamp 13-15px, Fragment Mono 11px tabular — fluid via clamp, measure 62-68ch, tracking -0.02em, balanced.

## Layout

Fluid to any device: CSS container queries + clamp. Map: fluid aspect 16/10 on mobile → 16/9 on tablet → 2/1 on ultra-wide, always inline. Ledger: container-query rail — 100% width <720px, 42% 720-1100px, 440px fixed >1100px, with fluid gap clamp(12px,2vw,20px). No breakpoint snapping, continuous flow.

## Elevation & Depth

Crisp 8px blur shadows at 0 8px 24px rgba(10,15,31,.10), 1px hairlines stay hairline at 200% zoom, no glass — clarity over blur.

## Shapes

8-14px radii, pill stops 999px, crosshair markers 7px saturated, star 10px, halo 12px at 0.12 opacity — all 1.2x more saturated than WELTARCHIV.

## Components

Signal tabs with 2px vermillion underline when on, live ticker with 8px mint pulse + 4px glow, ledger rows with 4px saturate bar + country flag, detail sheet with 2-col grid that collapses fluidly.

## Do's and Don'ts

- Do keep Discrimination Map name, world scope, and forensic ledger — now chromatic daylight, not muted paper
- Do keep fluid: clamp, cqi, container queries — no fixed 380px rail snapping
- Do keep saturation semantic: vermillion=live, steel=trust, mint=verified — not decoration
- Don't desaturate categories — push chroma, keep clarity
- Don't hide ledger behind modal on desktop — fluid rail stays visible
