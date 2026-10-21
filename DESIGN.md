---
name: Discrimination Map
description: Night observatory — a dark, calm instrument for documenting incidents on a map
colors:
  paper: "#070b14"
  paper-2: "#0e1424"
  surface: "#0b101d"
  ink: "#f0eadf"
  muted: "#b3b7c2"
  cyan: "#8fd8ea"
  vermillion: "#e11d2d"
  gold: "#e8b64c"
typography:
  display:
    fontFamily: "Sora, General Sans, system-ui, sans-serif"
  body:
    fontFamily: "General Sans, system-ui, sans-serif"
  mono:
    fontFamily: "Fragment Mono, ui-monospace, monospace"
    fontSize: "10-11px"
---

# Design System: DX-MAP (Discrimination Map) — Night Observatory

## Overview

**Creative North Star: "Night Observatory"**

The map is used on a phone, often outdoors at night or in a dim room, so the canvas is a tinted near-black blue (#070b14, never pure black) and the chrome recedes. All colour lives in the tokens at the top of `web/src/theme.css`; change the palette there and nowhere else. This replaces the earlier daylight "Signal Atlas" look on purpose. What stays: calm documentary voice, presumption of innocence ("documentation, not accusation"), no hype, safety by default.

## Colors

Canvas #070b14, raised surfaces #0b101d / #0e1424, hairlines are 1px at low alpha. Text is warm off-white (#f0eadf, 16:1 on the canvas), secondary #b3b7c2 (9.8:1), tertiary #9aa0af (7.5:1). One restrained ice-cyan (#8fd8ea) carries data readouts, the clock, counts and keyboard focus. Vermilion #e11d2d is reserved for live/new/alert, the report action and the top notice (white on it is 4.8:1). Category colours keep the palette from `lawref.py`; they are rendered glowing on the map and lifted toward white wherever they are used as text. Gold appears only in the brand lockup.

## Typography

Fragment Mono for readouts (clock, counts, ticker, tabs, labels), General Sans for reading text, Sora for display moments. No new fonts are loaded. Uppercase letter-spaced mono is limited to short labels; Arabic drops the letter-spacing.

## Layout

Rails, not panels. A narrow left rail of category toggles (icon plus count badge), a narrow right rail of actions (report, guide, awareness, table, law, locate), a top bar with the lockup, search, UTC clock and visible-incident count, a bottom-left render switch (GLOBE, 2D, MAP, SAT) above the timeline, and a full-width ticker of the latest incidents along the bottom. The sheet (incidents, table, law, symbols, get involved) sits beside the right rail on desktop and rises from the bottom on phones. On phones the left rail becomes a scrolling strip under the top bar. RTL mirrors every rail and the switch.

## Render views

GLOBE (MapLibre globe projection, dark), 2D (flat dark), MAP (the original light OpenFreeMap positron), SAT (NASA GIBS Blue Marble, public domain, with a dark scrim under the markers). The choice is remembered in localStorage; the default is GLOBE on desktop and 2D on touch and small screens. Switching swaps the style only, so data, filters, selection and the viewport stay put.

## Elevation & Depth

Flat. Depth comes from 1px hairlines and surface steps, not shadows or blur. No glassmorphism. Glow is allowed only on data (markers, network lines) and on the active control.

## Motion

The ticker scrolls slowly and pauses on hover and focus; control transitions are 150-180ms. Everything stops under `prefers-reduced-motion` (the ticker becomes a scrollable strip).

## Accessibility

Text at least 4.5:1, visible 2px focus ring in ice-cyan, 44px touch targets on touch devices, aria-labels on every icon-only control, the top notice dismisses by touch, keyboard and Esc and stays dismissed for the session.

