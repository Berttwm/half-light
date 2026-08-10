# Archive Masonry Redesign — Design Spec

Date: 2026-08-10
Status: approved mockup (FLOW=ROWS, ORDER=DARK-FIRST); pending spec review
Mockup: `docs/superpowers/specs/2026-08-10-archive-masonry-mockup/mockup.html` (serve the folder with any static server; thumbs load from the live site)

## Goal

Replace the contact sheet's fixed 3:2 grid (`site/contact.html`) with a Google-Images-style
masonry layout — natural aspect ratios, uniform column widths, rounded corners — and replace
the sheet ordering with DARK-FIRST. The projection reel (`site/index.html`) is untouched.

## Layout (`site/contact.html` + `site/assets/site.css`)

- **Masonry, rows flow.** JS places each photo into the currently-shortest column
  (track column height as a running sum of `h/w + 0.18`, where 0.18 approximates the two
  label rows in column-width units). This preserves approximate left-to-right reading order,
  which keeps the tonal arc flowing down the page as you scroll.
- **Column count:** `clamp(floor(containerWidth / 250), 2, 6)`; rebuild on resize when width
  changes by more than ~60px. The existing `<700px` mobile tweaks stay; the rule naturally
  yields 2 columns there.
- **Natural aspect ratios:** `width: 100%; height: auto` and per-image `width`/`height`
  attributes from data (prevents reflow). Delete the `aspect-ratio: 3/2` + `object-fit: cover`
  crop — that crop is the entire difference between the current square-ish look and the
  Google look.
- **Rounded corners:** `--radius: 14px` on card thumbs and the lightbox image. Gap between
  cards: 14px both axes.
- **Keep as-is:** edge label above / date below each frame, hover drift animation, glowpulse
  safelight ring (box-shadow follows border-radius automatically), dim-the-rest on hover
  (grid-level `:hover` + `opacity .32`), safelight edge color on hover, lightbox (incl.
  optional caption), keyboard access (tabindex, Enter/Space to open, Escape to close).
- **One deliberate change:** hover zoom 1.38 → **1.12**. Cells are ~3× taller at natural
  ratio; the old scale buried neighbouring cards. Tunable constant.
- No new dependencies; vanilla JS in the existing inline script.

## Ordering (`pipeline/compose.py`, sheet only)

Replace the single sort at the `sheet =` line with DARK-FIRST, no special cases:

1. **Night rack:** photos with `lum < 0.25`, sorted by `(lum, frame)`. 0.25 sits inside the
   archive's natural luminance gap (nothing between 0.161 and 0.347 across all 45 photos).
2. **Remainder:** serpentine band sort — key `(band, lum if band % 2 == 0 else -lum, frame)`.
   Even bands run dark→light, odd bands light→dark, so band seams stay continuous.

Rationale, from evaluation against the live archive:

- Hue is imperceptible at near-black, so band-first ordering misfiles dark frames
  (DSCF9836, lum 0.043, 3rd darkest of 45, was exiled to position 38 by its blue hue —
  a 0.49 luminance cliff against its neighbour).
- After DARK-FIRST the only luminance jumps left are the natural gap itself (0.161→0.347)
  and a mild 0.19 at the warm→green seam.
- `lum` stays **median-based; `analyze.py` is unchanged.** DSCF0112 (the lake) was evaluated
  as a suspected misread: five metrics tested (median, mean, p75, chroma-weighted
  Helmholtz–Kohlrausch, lit-area fraction) — all five rank it among the 8 darkest of 45.
  Its "daylight" read is scene semantics, not photometry. It stays in the night rack by
  measurement, at the rack tail, which is the transition point into the bright section anyway.
- The reel is unaffected: closer selection keeps using `lum` as-is; scenes don't use the
  sheet order.

Header copy `THE SHEET — EMBER TO ICE, DARK TO LIGHT` stays; the global arc (opens at the
darkest frame, ends ice-light) makes it more accurate than before.

## Tests (`pipeline/test_pipeline.py`)

- The existing sheet assertion (`sheet[0] == "DSCF0007"  # band 0, darkest first`) must be
  updated: first sheet entry is now the globally darkest photo regardless of band.
- Add: a dark cool-band photo (lum < 0.25) sorts into the night rack ahead of brighter
  warm-band photos; an odd-band group is ordered light→dark (serpentine).

## Build / deploy

- Run the pipeline build after the compose change; it regenerates the hashed
  `site/assets/data.<hash>.js` and rewrites the `<script src>` in both pages itself.
- Branch policy: work on `feature/archive-masonry`; master is SYNC-only — merge deliberately
  with `HALFLIGHT_SYNC=1 git merge feature/archive-masonry` from master. Cloudflare Pages
  auto-deploys master.

## Non-goals

- No changes to `site/index.html` (reel), `analyze.py`, grading, or thumbnails.
- No masonry library, no CSS `columns` (changes reading order to column-major), no native CSS
  masonry (not shipped cross-browser).
