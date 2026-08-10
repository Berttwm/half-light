# Archive Masonry Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Google-Images-style masonry archive page (natural ratios, rounded corners) with DARK-FIRST sheet ordering, shipped to half-light.pages.dev.

**Architecture:** Two independent changes meeting at build time: (1) `pipeline/compose.py` emits `sheet` in DARK-FIRST order (night rack + serpentine bands), baked into the hashed data file by `pipeline/build.py`; (2) `site/contact.html` + `site/assets/site.css` render that order as a rows-flow masonry (JS shortest-column placement). Spec: `docs/superpowers/specs/2026-08-10-archive-masonry-design.md`; approved visual reference: `docs/superpowers/specs/2026-08-10-archive-masonry-mockup/mockup.html`.

**Tech Stack:** Python 3 (pipeline, stdlib + PIL/numpy already present), vanilla JS/CSS (site). No new dependencies.

## Global Constraints

- Branch: all work on `feature/archive-masonry`; master is SYNC-only (guard hooks) — merge/push to master require env `HALFLIGHT_SYNC=1`.
- `site/index.html` (reel), `pipeline/analyze.py`, grading, thumbnails: untouched.
- Night rack threshold: `lum < 0.25` exactly. Serpentine key: `(band, lum if band % 2 == 0 else -lum, frame)`.
- Layout constants: radius 14px, gap 14px, hover zoom 1.12, columns `clamp(floor(width/250), 2, 6)`, label-height allowance `0.18`.
- Tests run with: `python pipeline\test_pipeline.py` (plain asserts, no pytest). Build: `python pipeline\build.py` from repo root.
- No new files in `site/`; no libraries.

---

### Task 1: DARK-FIRST sheet ordering in compose.py

**Files:**
- Modify: `pipeline/compose.py:52` (the `sheet =` line)
- Test: `pipeline/test_pipeline.py` (update `test_compose_rules`, add `test_compose_sheet_dark_first`)

**Interfaces:**
- Consumes: `photos` list of dicts with `id`, `frame`, `band` (0/1/2), `lum` (0..1) — unchanged.
- Produces: `compose(...)["sheet"]` — list of photo ids: night rack (lum < 0.25, by lum asc) first, then serpentine band sort. Consumed by `build.py` verbatim (no build.py change needed).

- [ ] **Step 1: Update the sheet assertion in `test_compose_rules` and add the new failing test**

In `test_compose_rules`, replace:

```python
    assert out["sheet"][0] == "DSCF0007"                     # band 0, darkest first
```

with (fixture lums: 7=.05, 1=.10 → night rack; rest serpentine — band0 asc 2,3,4,5; band2 asc 6,8):

```python
    assert out["sheet"] == ["DSCF0007", "DSCF0001", "DSCF0002", "DSCF0003",
                            "DSCF0004", "DSCF0005", "DSCF0006", "DSCF0008"]  # night rack, then serpentine
```

After `test_compose_rules`, add:

```python
def test_compose_sheet_dark_first():
    from pipeline import compose
    photos = [
        _mk(1, "2026.05.01", 3, 2, 0, .3, .30),   # warm mid
        _mk(2, "2026.05.02", 3, 2, 2, .8, .04),   # near-black cool -> night rack despite band 2
        _mk(3, "2026.05.03", 3, 2, 1, .3, .45),   # green
        _mk(4, "2026.05.04", 3, 2, 1, .3, .55),   # green, lighter
        _mk(5, "2026.05.05", 3, 2, 2, .4, .50),   # cool
        _mk(6, "2026.05.06", 3, 2, 0, .3, .60),   # warm light
    ]
    sheet = compose.compose(photos, {"reel_size": 14}, {})["sheet"]
    # night rack first (darkness beats hue), then warm asc, green DESC (serpentine), cool asc
    assert sheet == ["DSCF0002", "DSCF0001", "DSCF0006",
                     "DSCF0004", "DSCF0003", "DSCF0005"]
    print("ok test_compose_sheet_dark_first")
```

- [ ] **Step 2: Run tests to verify they fail**

Run (repo root): `python pipeline\test_pipeline.py`
Expected: AssertionError inside `test_compose_rules` (old band-first order) — the run stops at the first failure.

- [ ] **Step 3: Implement DARK-FIRST in compose.py**

Replace the line

```python
    sheet = [p["id"] for p in sorted(photos, key=lambda p: (p["band"], p["lum"], p["frame"]))]
```

with

```python
    # sheet: night rack first (hue is imperceptible near black), then ember->ice with
    # serpentine luminance per band so band seams stay continuous. 0.25 sits in the
    # archive's natural luminance gap (nothing between 0.161 and 0.347).
    dark = sorted((p for p in photos if p["lum"] < 0.25), key=lambda p: (p["lum"], p["frame"]))
    rest = sorted((p for p in photos if p["lum"] >= 0.25),
                  key=lambda p: (p["band"], p["lum"] if p["band"] % 2 == 0 else -p["lum"], p["frame"]))
    sheet = [p["id"] for p in dark + rest]
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python pipeline\test_pipeline.py`
Expected: `ALL TESTS PASSED` (includes the two updated/new compose tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/compose.py pipeline/test_pipeline.py
git commit -m "feat: DARK-FIRST sheet order (night rack + serpentine bands)"
```

### Task 2: Masonry layout on the archive page

**Files:**
- Modify: `site/contact.html` (strip builder + layout function in the inline script)
- Modify: `site/assets/site.css` (`:root`, Contact Sheet section, lightbox img)

**Interfaces:**
- Consumes: `window.SHEET` / `window.PHOTOS` from the data file (ids in DARK-FIRST order after Task 3's build; layout is order-agnostic).
- Produces: `.strip > .col > .frame` DOM (was `.strip > .frame`). Click/keyboard delegation on `#rolls` is unchanged and still matches `.frame` through the extra `.col` level.

- [ ] **Step 1: Rewrite the strip builder in `site/contact.html`**

Replace this block:

```js
  const sec = document.createElement('section');
  sec.className = 'roll';
  sec.innerHTML = '<h2>THE SHEET — EMBER TO ICE, DARK TO LIGHT</h2><div class="strip">' + photos.map(p =>
    '<div class="frame" tabindex="0" data-id="' + p.id + '">' +
    '<div class="edge">' + p.frame + 'A &middot; ' + TITLE + ' 400</div>' +
    '<img src="' + p.thumb + '" loading="lazy" style="background:#0b0b0b url(' + p.latent + ') center/cover">' +
    '<div class="date">' + p.date + '</div></div>').join('') + '</div>';
  holder.appendChild(sec);
```

with:

```js
  const sec = document.createElement('section');
  sec.className = 'roll';
  sec.innerHTML = '<h2>THE SHEET — EMBER TO ICE, DARK TO LIGHT</h2><div class="strip"></div>';
  holder.appendChild(sec);
  const strip = sec.querySelector('.strip');

  const frameHTML = p =>
    '<div class="frame" tabindex="0" data-id="' + p.id + '">' +
    '<div class="edge">' + p.frame + 'A &middot; ' + TITLE + ' 400</div>' +
    '<img src="' + p.thumb + '" width="' + p.w + '" height="' + p.h + '" loading="lazy" style="background:#0b0b0b url(' + p.latent + ') center/cover">' +
    '<div class="date">' + p.date + '</div></div>';

  // rows-flow masonry: place each photo into the currently-shortest column so the
  // DARK-FIRST order still reads left-to-right; heights tracked as h/w ratios
  // (+0.18 per card for the two label rows, in column-width units).
  function layout() {
    const n = Math.max(2, Math.min(6, Math.floor(strip.clientWidth / 250)));
    const cols = Array.from({ length: n }, () => ({ h: 0, html: '' }));
    photos.forEach(p => {
      const c = cols.reduce((a, b) => b.h < a.h ? b : a);
      c.html += frameHTML(p);
      c.h += p.h / p.w + 0.18;
    });
    strip.innerHTML = cols.map(c => '<div class="col">' + c.html + '</div>').join('');
  }
  let rw = innerWidth;
  addEventListener('resize', () => { if (Math.abs(innerWidth - rw) > 60) { rw = innerWidth; layout(); } });
  layout();
```

(If the current `<h2>` text differs, keep the file's existing text verbatim — only the builder changes.)

- [ ] **Step 2: Update `site/assets/site.css`**

In `:root`, add:

```css
  --radius: 14px;
```

Replace the `.strip` rule:

```css
.strip { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 2px; background: #0b0b0b; padding: 14px 2px; }
```

with:

```css
.strip { display: flex; gap: 14px; align-items: flex-start; padding: 14px 0; }
.strip .col { flex: 1; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
```

Replace the `.frame` padding rule:

```css
.frame { padding: 6px 4px; cursor: pointer; position: relative; transition: z-index 0s .18s, opacity .45s ease; }
```

with:

```css
.frame { cursor: pointer; position: relative; transition: z-index 0s .18s, opacity .45s ease; }
```

Replace the `.frame img` rule:

```css
.frame img { width: 100%; display: block; aspect-ratio: 3/2; object-fit: cover; filter: brightness(.96); transition: filter .25s, transform .3s cubic-bezier(.2,.9,.3,1.15), box-shadow .3s; }
```

with:

```css
.frame img { width: 100%; height: auto; display: block; border-radius: var(--radius); filter: brightness(.96); transition: filter .25s, transform .3s cubic-bezier(.2,.9,.3,1.15), box-shadow .3s; }
```

In the hover rule, change the zoom (1.38 → 1.12):

```css
.frame:hover img, .frame:focus-visible img { transform: scale(1.12); animation: glowpulse 2.4s ease-in-out .25s infinite; }
```

Add rounded corners to the lightbox image (in the `.lightbox img` rule, append `border-radius: var(--radius);`).

In the `@media (max-width: 700px)` block, delete the now-dead grid rule:

```css
  .strip { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
```

- [ ] **Step 3: Verify against the dev data locally**

Temporarily serve the repo's `site/` folder (any static server) and open `contact.html`.
Check against `docs/superpowers/specs/2026-08-10-archive-masonry-mockup/mockup.html` (FLOW=ROWS):
natural ratios, 14px radius/gaps, hover drift + safelight ring + dim-others still work,
lightbox opens (click and Enter), Escape closes, ~2 columns at narrow width.
Note: until Task 3 rebuilds the data file, the on-page ORDER is still the old one — layout only.

- [ ] **Step 4: Commit**

```bash
git add site/contact.html site/assets/site.css
git commit -m "feat: masonry archive layout (natural ratios, rounded corners)"
```

### Task 3: Build with the new order + full verification

**Files:**
- Modify (generated): `site/assets/data.<newhash>.js`, `site/index.html` + `site/contact.html` (script src swap by build), `site/photos/og.jpg` (rewritten byte-identical hero), `site/photos/.state.json` / `.manifest.json` / `.log.jsonl` (build bookkeeping)

**Interfaces:**
- Consumes: Task 1's compose output via `python pipeline\build.py`.
- Produces: deployed-ready `site/` where `window.SHEET` is DARK-FIRST (first id must be `DSCF0204`, with `DSCF9836` third).

- [ ] **Step 1: Run the full test suite, then the build**

Run (repo root): `python pipeline\test_pipeline.py` → expect `ALL TESTS PASSED`.
Run: `python pipeline\build.py` → expect `BUILD OK: 45 photos ...` (no new photos graded; incremental state).

- [ ] **Step 2: Verify the generated order**

Check the new `site/assets/data.<hash>.js`: `window.SHEET` must start
`["DSCF0204","DSCF0240","DSCF9836","DSCF0022", ...]` (night rack by darkness — 9836 third),
and both HTML pages must reference the new hash.

- [ ] **Step 3: Visual check of the built site**

Serve `site/` and confirm the archive page now opens with the near-black frames
(mannequin, ceramic, drummer) in the first rows, matching the approved mockup's DARK-FIRST view.

- [ ] **Step 4: Commit**

```bash
git add -A site/
git commit -m "build: regenerate data with DARK-FIRST sheet order"
```

### Task 4: Ship

**Files:** none (git only)

**Interfaces:**
- Consumes: complete `feature/archive-masonry` branch.
- Produces: updated `master` pushed to origin; Cloudflare Pages auto-deploys `site/` in ~1 minute.

- [ ] **Step 1: Merge to master (SYNC-guarded)**

```bash
git checkout master
HALFLIGHT_SYNC=1 git merge --no-ff feature/archive-masonry -m "feat: masonry archive + DARK-FIRST sheet (merge feature/archive-masonry)"
```

- [ ] **Step 2: Push (SYNC-guarded)**

```bash
HALFLIGHT_SYNC=1 git push
```

- [ ] **Step 3: Verify the live site**

After ~1-2 minutes, load https://half-light.pages.dev/contact.html — confirm masonry layout,
rounded corners, DARK-FIRST opening (0204 / 0240 / 9836 in the first rows), working hover
and lightbox. If the deploy hasn't propagated, retry once after another minute.

- [ ] **Step 4: Clean up**

```bash
git branch -d feature/archive-masonry
```
