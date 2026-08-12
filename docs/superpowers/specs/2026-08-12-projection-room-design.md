# The Projection Room — front-page design

**Date:** 2026-08-12 · **Status:** shipped · **Owner:** Bertrand + Claude
Settled over ten rounds of interactive mockups (`dev/claude/dumps/photo-showcase/mockups-front/`,
concept-f with room `BLEND` + intro `SPIRAL`). Research behind the decisions: three agent sweeps
covering recent photo-lookbook front pages, scroll-transition technique, and living/deformable
backgrounds.

## 1. What changed and why

The old reel spent scroll on an empty screen: every photo handed off through a black scrim, so half
of each transition showed nothing, and 1.15 viewport-heights per photo felt long because of it. The
rebuild keeps the darkroom identity and replaces the engine.

## 2. The scroll engine (binding)

- Scroll sets a **playhead**; the rendered value chases it through a lerp (0.10/frame,
  frame-rate compensated). Nothing maps scroll raw.
- **0.78 viewport-heights per scene.** Short, because no scroll is spent on blackness.
- **Idle snap**: 240 ms after scrolling stops, the page eases (380 ms, cubic-out) onto the nearest
  scene. Every rest state is a full print; the ride there is the visitor's.
- **Card over card**: the incoming print reaches opacity 1 while the outgoing is still fading and
  sliding away, 30vh above it. There is no dip to black, and no in-place cross-dissolve.
- `prefers-reduced-motion`: the playhead follows scroll directly, no snap, no drift, no letter
  spiral, and the CSS loops (echo spin, blob drift, dust) are stopped.

## 3. The lit room

Behind every print, derived from that photograph:

1. **Echo** — the photo's own 64px latent, scaled 1.7x, rotating once per 95 s under a radial mask.
   Its opacity peaks for mid-toned frames; its brightness is crushed and its saturation raised in
   proportion to the photo's luminance. Without that treatment a near-white frame smears the room
   grey, which is exactly what it used to do.
2. **Three blobs** — colours sampled at runtime from the latent on a 32x32 canvas: chroma-dominant
   weighting (a small vivid area beats a large washed-out one), near-grey and near-black pixels
   discarded, the two dominants forced at least 28° apart, plus a complement. Blob geometry and
   weighting carry a per-frame seed, so two near-identical photographs still get their own room.
3. **Dust, vignette, grain** — the room's air.

Room light **peaks for mid-toned photographs and recedes at both extremes**: a blazing print and a
near-black one both want the room to step back. It never reaches full black — the floor keeps a
hint of light in the darkest scene.

The room's parallax rides a **sine** of the playhead. A sawtooth (`t - round(t)`) reads identically
at rest but flips sign the instant the playhead crosses a midpoint — a visible ~45px lurch at every
scene boundary.

## 4. Presentation

- One print per scene, always, in the film rebate: emulsion tooth, sprocket strips, amber edge
  print (`HALF-LIGHT 400 · 0155A · 2026.05.30`). Frames are required; full-bleed was tried and
  rejected as inconsistent between portrait and landscape.
- The print is oversized **104%** inside its window so the inner drift has somewhere to travel.
  That drift is expressed in **percent of the print, never pixels** — the headroom is 2% of the
  print, which on a phone is about four pixels, so a pixel-based drift slides the image off its own
  window and exposes the frame beneath.
- Cursor depth: the frame tilts toward the pointer, its image counter-drifts, the room leans away.
  Touch devices get the same depth from scroll momentum instead.

## 5. Quotes

Quotes live in `config.json`. The reel rotates to the newest `reel_size` photos on every sync, so a
quote may never reference a photo id — it earns its frame by rule, in `compose.assign_quotes()`:

- one quote may carry `"prefer": "extreme"` and takes the most extreme-luminance print in the reel
  (the darkest or the brightest);
- the rest space themselves evenly through the remaining scenes;
- solo scenes only, never the hero, sides alternating left/right;
- each quote names its own `emphasis` words, which carry the safelight. The highlight marks the
  words that carry the line, not whichever word happens to fall last.

They sit in the print's margin, never over the image, and their words surface one by one as the
scene scrolls in, so a print is never on screen without its line underway. Below 700px the quote
stacks under the print. Lines are balanced so no single word is orphaned.

`assign_quotes()` is deliberately **separate** from `compose()`: the reel contract is asserted by
exact dict equality in the tests, so scene dicts stay byte-identical and quotes ride in their own
`window.QUOTES`.

## 6. Deliberately rejected

Recorded so they are not revived:

- **Dip-to-black transitions** — the original sin; half of every transition showed nothing.
- **Diptychs** — two prints in one viewport land too small to read and fight the
  one-photograph-at-a-time design. Removed from the composer, not hidden in the page.
- **Full-bleed photographs** — inconsistent between portrait and landscape; the frame is the
  fine-art read, and research agreed (Camille Mormal, Adoratorio, Okey Studio all mat their prints).
- **A WebGL fluid layer** (`webgl-fluid-enhanced`) — it paints dye *over* the background rather than
  displacing it, so it reads as a cursor effect floating on an unrelated backdrop.
- **A canvas paint-trail cursor** — left smeared residue.
- **EMULSION**, a hand-rolled flow-field displacing the latent — the right *idea* (the background's
  own pixels flowing), but rendered at a third of screen resolution and upscaled, which produced
  jagged stair-step artifacts. If it is ever revisited it must render at full device resolution.
- **Alternative frames** (mat, slab, float, paper, linen) and alternative intros (dust, projector).

## 7. Files

| File | Role |
|---|---|
| `site/index.html` | the whole front page: room, engine, scenes, quotes, chrome |
| `pipeline/compose.py` | `compose()` builds the reel (one print per scene); `assign_quotes()` binds quotes |
| `pipeline/build.py` | emits `window.QUOTES` alongside PHOTOS/SCENES/SHEET |
| `config.json` | `quotes[]` — text, emphasis words, optional `prefer` |
| `pipeline/test_pipeline.py` | `test_assign_quotes`, `test_compose_portraits_stay_solo` |
