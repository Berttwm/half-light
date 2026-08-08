# Photo Showcase — Design Spec

**Date:** 2026-08-08 · **Status:** approved-pending-review · **Owner:** Bertrand + Claude
**Approved through 8 rounds of interactive mockups** (reference implementation: `dev/claude/dumps/photo-showcase/mockups/`, visual/behavioral source of truth for the site build).

## 1. What this is

A pseudonymous, film-aesthetic showcase site for Bertrand's Fujifilm X100T photographs, publishing from `E:\Videos_Photos\X100T Photos\favorites` (SOOC JPG + RAF). Free hosting, near-zero maintenance: Bertrand double-clicks one SYNC script when he wants the site updated; everything else is automatic.

Working title/pseudonym: **"Half-Light"** — a placeholder stored as a single config value, swappable any time.

## 2. Goals (binding)

1. Two-view site: **The Projection Room** (cinematic scroll reel, 10–20 newest photos) + **The Contact Sheet** (full archive, tone-sorted).
2. **Consistency editor**: fully automatic grading pipeline giving every photo one confident vintage/film look — *bolder than minimum-touch* (Bertrand: SOOC files are intentionally dull; the grade adds color/life). Never destroys deliberate darkness (dark-scene guard).
3. **One-click sync**: `SYNC.bat` inside the favorites folder → analyze/grade/build/commit/push → Cloudflare Pages auto-deploys. No scheduled tasks, no human steps beyond the double-click.
4. Free hosting: Cloudflare Pages, private GitHub repo (limits verified: 500 builds/mo, 20k files, 25 MiB/file — ample).
5. 100% phone-compatible; award-site motion standards (see §5); mystique-first design language.

## 3. Repository layout

```
photo-showcase/
├── config.toml            # pseudonym/title, look knobs, reel size, paths
├── pipeline/              # Python: analyze + grade + compose + build
│   ├── build.py           # single entry point: full sync build
│   ├── grade.py           # consistency editor (§4)
│   ├── analyze.py         # shared analysis: hue band, median lum, tint (§6)
│   ├── compose.py         # auto-composer scene rules (§7)
│   └── test_pipeline.py   # self-check on bundled sample images
├── site/                  # deployed static site (Cloudflare Pages root)
│   ├── index.html         # Projection Room
│   ├── contact.html       # Contact Sheet
│   ├── assets/…           # css/js
│   └── photos/            # graded WebP: full/2048, thumb/1024, latent/tiny-blurred
├── overrides.json         # optional per-photo curation (captions, skip, exposure, pairing)
├── deploy/SYNC.bat        # copied/linked into the favorites folder
└── docs/superpowers/specs/
```

Originals never leave `E:`; the repo holds only graded derivatives. `.gitignore` excludes any raw source copies.

## 4. Consistency editor (grading pipeline)

Order per photo (research-validated, see STATUS.md for sources):

1. **Decode**: SOOC JPG directly; RAF via `rawpy.extract_thumb()` (embedded full-size JPEG — no demosaic). Same-stem JPG+RAF → prefer RAF.
2. **EXIF orientation transpose** (`ImageOps.exif_transpose`) — mandatory; round-1 mockups shipped sideways portraits without it.
3. **Auto-straighten**: Canny + `HoughLinesP` on downscaled center band; length-weighted median angle; consensus gate (inlier length ≥ 0.8×width, weighted std ≤ 0.7°); skip if |angle| < 0.3° or > 4.0°; rotate full-res + inscribed-rect crop; require ≥ 88% area retained else skip. No-horizon scenes untouched by construction.
4. **Conservative WB**: Shades-of-Gray (p=6, clipped pixels excluded), applied at strength 0.3, gains hard-clamped to ±6%. Film-sim character is the look; this only reels in outliers.
5. **Exposure lift**: luminance median → gamma targeting 0.42, exponent clamped [0.60, 1.0] (lift-only, ≤ ~1.3 stops), ratio-preserving with per-pixel highlight limiter (cannot clip). **Dark-scene guard**: median < 0.02 → skip entirely (e.g. DSCF0204, median 0.008); median < 0.08 → halve lift.
6. **The look** (frozen, identical for every photo): one 33³ LUT via Pillow `Color3DLUT` — faded blacks (~0.05), rolled highlights, rich split-tone (shadows teal-green, highlights warm), saturation shaping with highlight desat. **Tuned bolder** per Bertrand's directive during a one-time look-calibration pass on his real set (the only human taste input; frozen thereafter).
7. **Finish** at output resolution: resize 2048 Lanczos → vignette (~0.22 EV) → warm halation (screen blend) → film grain last (blurred-Gaussian σ≈0.9px, luminance-modulated, luma-only) → WebP q85 m6.
8. **Outputs per photo**: `full/` 2048, `thumb/` 1024, `latent/` ~64px heavily blurred (placeholder + strip-gate latent state — no runtime CSS blur on mobile).
9. **Guardrails**: per-photo try/except with no-edit fallback; clip-fraction and output-size gates; atomic writes (`.tmp` + `os.replace`); idempotent (skip if source hash unchanged); one JSONL log line per photo per run.

Dependencies: pillow, numpy, rawpy, exifread (present) + `opencv-python-headless`, `pillow-lut-tools`. Python 3.8-compatible.

## 5. The Projection Room (site/index.html)

Round-8 motion system — **built from award-site research and cross-verified; these are contracts, not suggestions**:

- **Inertia layer**: scroll sets target; rendered value chases at lerp 0.10/frame (frame-rate-compensated). Nothing maps scroll raw.
- **One transition language**: dip-to-black crossfade (fixed black scrim peaking 0.45 at scene midpoints; slide opacity slope 2.2 so photos barely overlap) + continuous micro-zoom 1.00↔1.06 linear.
- **Inner parallax**: every photo 116% oversized inside an overflow-hidden window, translateY depth 32–58px varying per image.
- **Exactly two clip-mask set pieces per reel**: letterbox `inset(45%→0)` on the hero; iris `circle(18%→100%)` on one designated mid-reel solo.
- **Forbidden** (research tacky-markers): rotation on photos, blur/brightness filters as transitions, scale outside [1.0, 1.06] (settle-in max 1.2), non-monotonic easing on scrubbed motion, per-scene effect variety.
- Scene types: text (intro with per-letter scatter-on-exit; end card), solo, diptych (hue-paired verticals), strip (all-landscape, uniform height, oversized, pans through the gate; frames light by own position via **opacity** 0.25→1).
- Presentation: every photo in the film-rebate `.neg` frame (sprockets + amber edge-print `0018A · 2026.05.28`, 9.5px mono, .1em tracking; edge print lands a beat after the image).
- Backdrop layers: per-scene dominant-tint background drift + tint-following projector glow (tint ×3.1, α .22, dual-layer crossfade) + radial vignette + grain texture + 14 drifting dust motes + blurred-self photo spill.
- Chrome: italic-serif title, CONTACT SHEET link, frame counter `NN / NN`, progress rail with amber dot, scroll hint.
- Intro line: *"the inner machinations of a photographic mind are an enigma"* (single line on desktop).
- Mobile (≤700px): portraits near-full-bleed, diptychs stay side-by-side, strip goes vertical, px-based scroll segments (URL-bar-safe), no horizontal overflow.
- Reel content: newest `reel_size` photos (config, default 14, range 10–20). Lazy-load by scroll proximity with latent placeholders. `prefers-reduced-motion`: static reveals, no scatter/parallax.

## 6. Shared analysis + data

`analyze.py` runs on **graded** output (one analysis feeding both site and composer — no divergence):
- hue band (warm <60°|≥330°, green, cool), median luminance, dominant-hue dark tint (for backgrounds) and brightened glow tint.
- Manifest `site/assets/data.<contenthash>.js` (`window.PHOTOS`); HTML references rewritten each build → cache-safe by construction (caching bug bit twice in mockups).

## 7. Auto-composer (compose.py)

Deterministic scene assembly per build — automation must not degrade the art direction:
1. Reel = newest N by capture date (EXIF).
2. Hero = newest photo, solo + letterbox.
3. Portrait pairing: adjacent-in-reel portraits in the same hue band → diptych (max 2 diptychs); horizons/tonal echo approximated by band+lum proximity.
4. Landscape runs: ≥3 same-band landscapes → one strip (max 1).
5. Iris: the most-saturated cool solo, else middle solo.
6. Closer: lowest-luminance photo, solo, placed last.
7. Everything else: solos, capture order.
8. `overrides.json` may pin/skip/pair any photo (optional curation, auto by default).
Contact sheet: all photos, sorted band → luminance ("ember to ice, dark to light"), month-agnostic single sheet.

## 8. The Contact Sheet (site/contact.html)

As round-8 mockup: grid of edge-printed frames on charcoal; hover = 1.38× bulge with organic drift path + pulsing amber glow (1px box-shadow ring riding the image edge) while all sibling frames dim to 0.32; click = full-bleed lightbox (develop-in animation, blurred-self ambient fill, `No. NNNN · date · X100T` — no film-sim text). Fully touch-functional (tap = lightbox). This page is also the reduced-motion/no-frills fallback view.

## 9. Sync + deploy

- `SYNC.bat` (lives in the favorites folder): activates venv → `python pipeline/build.py` → on success `git add/commit/push` → prints per-photo summary from the JSONL log → `pause`. Non-zero exit + red text on failure; never half-publishes (build fails atomically if >25% of photos error).
- Cloudflare Pages: private GitHub repo, project root `site/`, no build command. **One-time setup by Bertrand** (GitHub push + Cloudflare account/link) with a step-by-step README; everything after is the SYNC click.
- OG/social: og:image = hero graded photo, og:title = pseudonym, description one mystique line. Discoverable when shared, withheld otherwise.

## 10. Testing

- `test_pipeline.py` (stdlib assert-based): runs the full pipeline on bundled tiny fixtures — an underexposed sample, a tilted-horizon sample, a near-black sample (must be skipped by the guard), an orientation-6 sample (must transpose) — and asserts output existence, no clipping increase, rotation within cap, idempotent re-run. One command, no framework.
- Site: keep the `__render(t)` deterministic probe hook from the mockups; a probe script asserts the §5 motion contracts (no rotate, scale bounds, scrim peak, mask ranges).
- Real-device iOS pass after first deploy (flagged risk: scroll-linked animation perf; latent images pre-rendered specifically to avoid runtime blur).

## 11. Out of scope / later

- Real pseudonym (config swap when chosen).
- The Darkfield (round-2 infinite canvas) — shelved, revisitable.
- Film-sim name extraction from Fuji MakerNote; Cloudflare Web Analytics; custom domain.

## 12. Open questions

None blocking. The one-time human inputs remaining: look-calibration approval (§4.6) and Cloudflare/GitHub account linkage (§9).
