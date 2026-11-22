# Design system

The brief (CLAUDE.md §5) fixes the direction: calm and modern like Linear or Vercel, neutral
greys plus **one** accent, an Inter-like typeface, a 4/8 px spacing scale, rounded-xl cards,
subtle borders instead of shadows, light and dark themes. Inside that, these are the choices
made for GateSense and why.

## The one memorable thing: the plate chip

Every vehicle in the app is drawn as a small Indian high-security registration plate (HSRP):
white plate, thin black border, the blue "IND" strip on the left, the number in a condensed
bold face, grouped the way it is printed (`UP16 AB 1234`, `22 BH 1234 AA`). The plate stays
white in the dark theme too, because real plates are white; on the night-shift guard console
it is the brightest thing on screen, which is exactly what a guard scans for.

Everything else is deliberately quiet so the plates carry the identity.

## Colour

One accent, taken from the plate itself: the blue of the IND strip.

| Token | Light | Dark | Used for |
|---|---|---|---|
| `bg` | `#F7F8FA` | `#111317` | page background |
| `surface` | `#FFFFFF` | `#171A1F` | cards, tables, inputs |
| `surface-2` | `#F1F3F6` | `#1E2228` | hover rows, subtle fills |
| `border` | `#E3E6EB` | `#2A2F37` | every outline (no shadows) |
| `text` | `#15181D` | `#E8EBEF` | body text |
| `muted` | `#5B6470` | `#A0A8B3` | secondary text (AA on both surfaces) |
| `accent` | `#2147C9` | `#7A97FF` | links, focus rings, primary buttons |

Status colours are not "accents": they only ever mean a state. Green = approved / allowed,
amber = running late (overstay), red = denied / watchlist. They always come with a word or
an icon as well, never colour alone.

## Type

- **IBM Plex Sans** for everything: close to Inter in tone, with more character in the
  figures. Its sibling **IBM Plex Sans Devanagari** is designed to match, so the guard
  console's Hindi mode looks native instead of falling back to a system font.
- **IBM Plex Sans Condensed** (semibold) only inside plate chips.
- Scale (1.25 ratio): 12 · 14 (dashboard body) · 16 (landing body) · 20 · 25 · 31 · 39 px.
  Figures are tabular wherever numbers line up (counters, tables, times).
- Sentence case everywhere; no all-caps labels.

## Shape and space

- 4 px base unit; most gaps are 8, 12, 16 or 24 px.
- Radius has a hierarchy: cards `rounded-xl` (12 px), buttons and inputs `rounded-lg`
  (8 px), plate chips 4 px (like the real thing), status badges fully rounded.
- 1 px borders separate things; shadows appear only on floating layers (dialogs, toasts).

## Per area

- **Guard console:** dark by default, large touch targets (min 44 px, primary actions
  56 px), at most two taps for the common actions, English / हिन्दी toggle. Three columns at
  1280 px (arrivals · waiting for a decision · alerts and calls); tabs on a phone.
- **Resident app:** mobile-first PWA with a bottom tab bar. Approve / Deny are full-width
  buttons with a visible countdown.
- **Admin:** sidebar layout, tables with search, filters and pagination, charts in the
  same neutral palette with the accent for the main series.

## Motion

One orchestrated moment: on the landing page, plates arrive one by one into the sample
gate feed. Elsewhere motion only answers an action (a card leaving after Approve, a dialog
opening). Everything respects `prefers-reduced-motion`.
