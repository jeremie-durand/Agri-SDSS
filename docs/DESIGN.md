---
name: MOS-GIS
description: Geospatial data platform for sustainable agriculture research in Quebec
colors:
  bg: "#0f1117"
  surface: "#1a1d27"
  surface-hover: "#22263a"
  border: "#2a2e45"
  accent: "#3ecf8e"
  accent-dim: "#1e7a52"
  text-primary: "#e8eaf0"
  text-secondary: "#8b92a8"
  text-muted: "#555d78"
  service-stac: "#3b82f6"
  service-raster: "#f59e0b"
  service-vector: "#8b5cf6"
  service-pygeoapi: "#10b981"
  service-browser: "#ec4899"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif"
    fontSize: "1.6rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif"
    fontSize: "0.98rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif"
    fontSize: "0.85rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "'SFMono-Regular', Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 600
    letterSpacing: "0.1em"
rounded:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "10px"
spacing:
  xs: "0.4rem"
  sm: "0.85rem"
  md: "1.25rem"
  lg: "1.5rem"
  xl: "2.5rem"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.bg}"
    rounded: "{rounded.sm}"
    padding: "0.45rem 1rem"
  button-primary-hover:
    backgroundColor: "#5adeaa"
    textColor: "{colors.bg}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "0.45rem 1rem"
  button-ghost-hover:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.text-primary}"
  service-card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: "{spacing.lg}"
  service-card-hover:
    backgroundColor: "{colors.surface-hover}"
  badge:
    rounded: "{rounded.xs}"
    padding: "0.18rem 0.55rem"
---

# Design System: MOS-GIS

## 1. Overview

**Creative North Star: "The Observatory"**

MOS-GIS is a dark-mode precision instrument. Its surfaces are the control room of a research observatory: deep black-blue voids, instrument panels that reveal data on demand, and a single signal-green acquisition color that marks what is live, active, and reachable. Nothing glows for decoration. Every lit element has a reason. Researchers and agronomists arrive here to locate, inspect, and retrieve geospatial data — the interface should never compete with the data it presents.

The aesthetic is neither developer-tool austere nor enterprise-platform heavy. It is a calm, public-facing scientific interface. Density is moderate. Typography is clear and purposeful. The service grid is the primary interaction surface — each card a gateway — and it must communicate function and status without ambiguity.

This system explicitly rejects heavy enterprise GIS aesthetics: crowded navigation, tiny muted text, navy-on-gray palettes that feel like a 2009 government intranet. It equally rejects flashy SaaS conventions: no hero metrics, no gradient blobs, no glassmorphism, no startup-voice copy.

**Key Characteristics:**
- Dark surfaces with tonal depth (background → surface → surface-hover), no shadows
- One signal accent (Acquisition Green) used sparingly for active states and primary actions
- Service-specific colors scoped to badges only — never bled into layout
- System font stack (Inter/SF/Segoe) — legible and neutral, letting data carry weight
- French primary voice, calm and direct, no marketing language

## 2. Colors: The Observatory Palette

A restrained dark palette built around one active signal. The void is the canvas; the accent is the beacon.

### Primary
- **Acquisition Green** (`#3ecf8e`): The single live-system signal. Used for primary buttons, the active status dot, the accent portion of the wordmark, and link text in footer. Its rarity is the point — when it appears, something is actionable or alive.
- **Dimmed Acquisition** (`#1e7a52`): The shadow of the signal. Background tint for accent-adjacent contexts. Not used directly in the current codebase — reserve for focus rings or pressed states on the primary button.

### Neutral
- **Deep Space Black** (`#0f1117`): Page background. The void. Nothing sits on it except structured surfaces.
- **Instrument Panel** (`#1a1d27`): Default surface. Where cards and the header live.
- **Elevated Surface** (`#22263a`): Hover state for surfaces. The only elevation mechanism — tonal shift, never shadow.
- **Void Line** (`#2a2e45`): Borders and dividers. Barely visible — structural, not decorative.
- **Starlight** (`#e8eaf0`): Primary text. Sufficient contrast against all dark surfaces.
- **Twilight** (`#8b92a8`): Secondary text. Used for descriptions, sub-labels, and ghost button text. Verify 4.5:1 before applying at small sizes.
- **Void Text** (`#555d78`): Muted text only. Endpoint URLs, footer copy, placeholder text. Never body text.

### Service Accents (scoped)
Per-service colors exist exclusively inside badge chips and card icon backgrounds. They identify which standard or protocol a service implements. They are never used for layout, type, or interactive states outside their own card.
- **Cartesian Blue** (`#3b82f6`): STAC API — catalogue and spatial indexing
- **Thermal Amber** (`#f59e0b`): Raster API — COG tiles and coverage
- **Geodesic Violet** (`#8b5cf6`): Vector API — features and geometries
- **Process Emerald** (`#10b981`): PyGeoAPI — OGC processes and EO
- **Interface Pink** (`#ec4899`): STAC Browser — the frontend explorer

**The One Signal Rule.** Acquisition Green (`#3ecf8e`) is the only color that communicates interactivity or live status outside of service badges. If a new interactive element appears on the page, its active/live state uses this color. No other color takes that role.

**The Scoped Badge Rule.** Service accent colors (Cartesian Blue, Thermal Amber, Geodesic Violet, Process Emerald, Interface Pink) are badge-only. They do not migrate to headings, borders, backgrounds, buttons, or any element outside a `.card-badge` or `.card-icon` context.

## 3. Typography

**Body / UI Font:** System stack — `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif` (no web font loaded; Inter when present, SF Pro on macOS, Segoe on Windows)
**Mono Font:** `'SFMono-Regular', Consolas, monospace` — used for endpoint URLs and code tokens only

**Character:** A single sans-serif family across all weights. No display/body split — hierarchy is entirely through weight (400 → 600 → 700) and scale. Clean, neutral, system-native. The typeface defers to the data; it never asserts personality of its own.

### Hierarchy
- **Display** (700, 1.6rem, lh 1.2, ls -0.02em): The wordmark `MOS-GIS` in the header only. One instance per page.
- **Title** (600, 0.98rem, lh 1.3): Card titles and section headings. Used sparingly — one title per card.
- **Body** (400, 0.85rem, lh 1.6): Card descriptions and header tagline. Max line length 65ch. The primary reading weight for all prose content.
- **Label** (mono, 600, 0.75rem, ls 0.1em, uppercase): Section labels (`Services disponibles`) and endpoint URLs. Uppercase reserved for short labels of ≤4 words.

**The Single-Family Rule.** No second typeface is introduced. Not for headings, not for decorative purposes, not for "personality". The weight and size hierarchy is the typography. Adding a display serif would fight with the Observatory's instrument-precision character.

## 4. Elevation

This system uses no shadows. Depth is conveyed exclusively through tonal surface shifts: `--bg` (deepest) → `--surface` (resting card) → `--surface-hover` (active/hovered card). The dark voids between surfaces replace shadow as a separation mechanism.

Borders (`--border: #2a2e45`) add structural separation where surfaces meet — header from main, footer from main — but are intentionally low-contrast: visible as structure, invisible as decoration.

**The Flat-By-Default Rule.** No `box-shadow` on cards, buttons, or containers at rest or on hover. If a floating element appears (dropdown, tooltip, modal), it uses a single very subtle shadow — `0 8px 32px rgba(0,0,0,0.5)` — against the dark background. This is the only permitted shadow, and only for elements that truly float above the document flow.

## 5. Components

### Buttons
Compact, legible, purpose-first. States are immediate — 150ms transitions. No animation on layout properties.
- **Shape:** Gently rounded (6px). Reads as "precise tool button", not "rounded consumer app".
- **Primary (`btn-primary`):** Acquisition Green background (`#3ecf8e`), Deep Space Black text (`#0f1117`), 1px solid border matching background. Hover: brightens to `#5adeaa`. Font size 0.85rem, weight 500, padding 0.45rem 1rem.
- **Ghost (`btn-ghost`):** Transparent background, Twilight text (`#8b92a8`), Void Line border (`#2a2e45`). Hover: Elevated Surface background, Starlight text, slightly lighter border. Used for secondary actions (Docs, Collections links).
- **GitHub (`btn-github`):** Elevated Surface background, Twilight text, Void Line border. Hover: slightly lighter. Used for the single external repo link.

**Focus ring (all buttons):** `outline: 2px solid #3ecf8e; outline-offset: 2px` — WCAG 2.1 AA compliant.

### Service Cards
The primary content unit. Each card is one service entry point.
- **Corner Style:** Gently curved (10px) — slightly more rounded than buttons, creates visual softness without being consumer-app round.
- **Background:** Instrument Panel (`#1a1d27`) at rest; Elevated Surface (`#22263a`) on hover.
- **Border:** Void Line (`#2a2e45`) at rest; slightly lighter (`#3a3f5c`) on hover.
- **Shadow:** None.
- **Internal Padding:** 1.5rem all sides.
- **Card actions:** A row of buttons below the description — primary action first ("Ouvrir" / "Endpoint"), secondary ghost actions after (Docs, Collections). Never more than 4 action buttons per card.

### Badges
Service protocol identifiers, not status indicators.
- **Style:** Colored background + matching text from the service accent palette. Radius 4px. Font 0.7rem, weight 600, uppercase, ls 0.04em.
- **Context:** Always inside a card header, below the card title. Never used as standalone status chips outside cards.

### Card Icons
40×40px rounded square (8px radius). Background is a dark tinted version of the service accent color (e.g. `#0f1e3d` for blue). Icon is an SVG stroke in the service accent color. Provides visual identity without dominating.

### Navigation
There is currently no top navigation component. If one is introduced: it inherits the header pattern — Instrument Panel background, Void Line bottom border, Starlight active link, Twilight inactive link with hover to Starlight. No dropdown-heavy menus; the services are enumerated on the home page.

### Endpoint URL
A monospaced label below the card description showing the service URL pattern.
- **Style:** Mono font, 0.75rem, Void Text color (`#555d78`), with a 6px Acquisition Green dot as a live-indicator prefix.
- **The dot** communicates "this endpoint is reachable" — it is the only non-accent use of `#3ecf8e` that is not interactive.

## 6. Do's and Don'ts

### Do:
- **Do** use Acquisition Green (`#3ecf8e`) for primary buttons, active status indicators, wordmark accents, and focus rings. Nothing else.
- **Do** keep service accent colors (blue, amber, violet, emerald, pink) inside card badges and icon backgrounds only.
- **Do** convey depth through tonal surface shifts (bg → surface → surface-hover). No shadows on cards or containers at rest.
- **Do** keep body text at `#e8eaf0` on dark surfaces — never drop to `#8b92a8` for running descriptions (WCAG AA).
- **Do** use the system font stack. No web fonts unless a specific typographic need is identified and confirmed.
- **Do** limit uppercase to labels of 4 words or fewer (section headers, badge text, endpoint mono labels).
- **Do** respect `prefers-reduced-motion`: every transition has an `@media (prefers-reduced-motion: reduce)` override.
- **Do** write UI copy in French first, direct and brief — no tech buzzwords in visible labels.

### Don't:
- **Don't** use dense enterprise GIS aesthetics: crowded navigation, tiny muted body text, navy-on-gray color palettes. The reference is an instrument panel, not ArcGIS Portal or an Oracle forms UI.
- **Don't** introduce SaaS dashboard conventions: no gradient blobs, no glassmorphism cards, no `background-clip: text` gradient headings, no hero-metric templates with big numbers and stat rows.
- **Don't** add a second typeface. Not for "character", not for "warmth". The system-font hierarchy carries all needed differentiation.
- **Don't** use `box-shadow` on cards or buttons. The flat tonal system is intentional — adding shadows breaks the Observatory character.
- **Don't** bleed service accent colors outside their card. Cartesian Blue, Thermal Amber, Geodesic Violet, Process Emerald, and Interface Pink are identifiers — they are not a general color vocabulary.
- **Don't** use Void Text (`#555d78`) for body content. It is for supplementary metadata only (endpoint URLs, footer copy). Body text minimum is Twilight (`#8b92a8`) — verify contrast at the specific size before using it for running prose.
- **Don't** use `border-left` or `border-right` as a colored accent stripe on cards or callouts. Background tints or icon treatment replace it.
- **Don't** uppercase body sentences. Uppercase is for labels (≤4 words), badges, and endpoint mono text only.
