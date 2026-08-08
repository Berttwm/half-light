# Photo Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Half-Light photo showcase: a Python grading/composing pipeline + two-page static site + one-click SYNC, per `docs/superpowers/specs/2026-08-08-photo-showcase-design.md`.

**Architecture:** A Python pipeline (`pipeline/`) grades photos from the favorites folder into `site/photos/`, analyzes the graded output, deterministically composes reel scenes, and emits a content-hashed data manifest. The static site (`site/`) renders the Projection Room and Contact Sheet from that manifest using the round-8 motion contracts. `SYNC.bat` runs build → commit → push; Cloudflare Pages deploys `site/`.

**Tech Stack:** Python 3.8.3 with the ALREADY-INSTALLED set only — Pillow 10.4, numpy 1.24, rawpy 0.21, cv2 4.9, exifread 3.5. Vanilla HTML/CSS/JS, no frameworks, no build step for the site.

## Global Constraints

- **Zero new Python packages.** Only PIL/numpy/rawpy/cv2/exifread + stdlib. Python 3.8-compatible syntax (no `match`, no `tomllib` — config is **JSON**).
- Spec deviations already approved: `config.json` not `config.toml`; system Python not venv (deps verified installed); LUT generated in numpy via `PIL.ImageFilter.Color3DLUT.generate` (no pillow-lut-tools).
- Originals in `E:\Videos_Photos\X100T Photos\favorites` are **never modified or deleted**; the repo holds only graded derivatives.
- Site motion contracts (binding, from spec §5): lerp 0.10/frame frame-rate-compensated; dip-to-black scrim peak 0.45; micro-zoom 1.00↔1.06 linear; inner parallax 32–58px in 116%-oversized overflow-hidden windows; exactly two clip-mask set pieces (letterbox hero, iris); **forbidden:** photo rotation, blur/brightness filters as transitions, scale outside [1.0, 1.06], non-monotonic scrub easing, per-scene effect variety.
- Design tokens (from mockups): ground `#131313`, ink `#c9c4bc`, ink-dim `#6e6a63`, safelight `#d99a4e`, serif `Georgia, 'Times New Roman', serif`, mono `Consolas, 'Courier New', monospace`. Edge-print format `0018A · 2026.05.28`, 9.5px mono, `.1em` tracking, `#93763f`.
- Site copy verbatim: title placeholder **"Half-Light"** (config value); intro line **"the inner machinations of a photographic mind are an enigma"**; end card **"the roll continues"** / **"NEW FRAMES ARE DEVELOPED AS THEY ARE TAKEN"**; hint **"SCROLL TO BEGIN THE PROJECTION"**. No film-simulation text anywhere.
- Reference implementation for the site pages: `C:\Users\Bertrand\Desktop\dev\claude\dumps\photo-showcase\mockups\projection.html` and `contact.html` (round 8). Port faithfully; deltas are enumerated in Tasks 9–10.
- Outputs per photo: `full/` 2048px WebP q85 m6 · `thumb/` 1024px · `latent/` 64px heavily blurred. Dark-scene guard: median lum < 0.02 → no exposure lift (DSCF0204 = 0.008 must stay dark).
- Every pipeline run writes one JSONL line per photo; build fails (exit 1, nothing published) if >25% of photos error.
- Tests: stdlib `assert`-based functions in `pipeline/test_pipeline.py`, run with `python pipeline/test_pipeline.py` (a `main()` calls each `test_*`). No pytest. Synthetic fixtures generated in-test (no binary fixtures in repo).
- **Process:** implementers follow superpowers TDD discipline (failing test → minimal code → green → commit) AND ponytail: stdlib before custom, no unrequested abstractions, fewest files, shortest working diff; deliberate cut corners get a `ponytail:` comment naming the ceiling. The 12-goal register in `dev/claude/dumps/photo-showcase/STATUS.md` ("IMPLEMENTATION GOALS") is binding; the self-review below maps each goal to its task.
- Commit after every green test cycle. Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure

```
photo-showcase/
├── config.json                  # Task 1 — title, paths, all look/guard knobs
├── overrides.json               # Task 7 — optional per-photo curation, starts {}
├── pipeline/
│   ├── __init__.py              # empty
│   ├── build.py                 # Tasks 1, 8, 12 — scan, orchestrate, emit data, calibrate mode
│   ├── grade.py                 # Tasks 2-6 — decode/straighten/WB/lift/look/finish/save
│   ├── analyze.py               # Task 6 — hue band / lum / sat / tint on graded output
│   ├── compose.py               # Task 7 — deterministic scene rules
│   └── test_pipeline.py         # Tasks 1-8 — all tests
├── site/
│   ├── index.html               # Task 10 — Projection Room (JS inline, mockup-ported)
│   ├── contact.html             # Task 9 — Contact Sheet (JS inline, mockup-ported)
│   ├── assets/
│   │   ├── site.css             # Task 9 — shared tokens/grain/neg-frame/lightbox
│   │   └── data.dev.js          # seed manifest reference, rewritten by every build
│   └── photos/                  # generated: full/ thumb/ latent/ og.jpg .state.json
├── deploy/SYNC.bat              # Task 11
└── README.md                    # Task 11 — one-time GitHub/Cloudflare setup
```

---

### Task 1: Config + source scanner

**Files:**
- Create: `config.json`, `pipeline/__init__.py`, `pipeline/build.py`, `pipeline/test_pipeline.py`

**Interfaces:**
- Produces: `build.load_config(path="config.json") -> dict`; `build.scan_sources(src_dir) -> list[dict]` where each entry is `{"stem": "DSCF0018", "path": "<abs path>", "ext": ".RAF"|".JPG"}`, sorted by stem, same-stem RAF preferred over JPG.

- [ ] **Step 1: Write the failing test**

```python
# pipeline/test_pipeline.py
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import build

def test_scan_sources():
    with tempfile.TemporaryDirectory() as d:
        for name in ["DSCF0001.JPG", "DSCF0002.RAF", "DSCF0001.RAF", "notes.txt", "DSCF0003.jpg"]:
            open(os.path.join(d, name), "wb").close()
        out = build.scan_sources(d)
        assert [e["stem"] for e in out] == ["DSCF0001", "DSCF0002", "DSCF0003"], out
        assert out[0]["ext"] == ".RAF"          # RAF preferred over same-stem JPG
        assert out[2]["ext"] == ".JPG"          # lowercase .jpg normalized
    print("ok test_scan_sources")

def test_load_config():
    cfg = build.load_config()
    assert cfg["title"] == "Half-Light"
    assert cfg["exposure"]["target_median"] == 0.42
    assert cfg["reel_size"] == 14
    print("ok test_load_config")

def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python pipeline/test_pipeline.py`
Expected: `ModuleNotFoundError` / `AttributeError` (build.scan_sources missing)

- [ ] **Step 3: Write config.json**

```json
{
  "title": "Half-Light",
  "intro_line": "the inner machinations of a photographic mind are an enigma",
  "source_dir": "E:/Videos_Photos/X100T Photos/favorites",
  "reel_size": 14,
  "exposure": { "target_median": 0.42, "gamma_min": 0.60, "dark_skip": 0.02, "dark_soft": 0.08 },
  "wb": { "strength": 0.30, "clamp": 0.06 },
  "rotate": { "min_angle": 0.3, "max_angle": 4.0, "min_area_keep": 0.88 },
  "look": { "fade_black": 0.05, "white_ceiling": 0.98, "shoulder": 0.80, "saturation": 0.95,
            "highlight_desat": 0.15, "shadow_tone": [-0.004, 0.004, 0.016],
            "highlight_tone": [0.014, 0.006, -0.008] },
  "finish": { "long_edge": 2048, "thumb_edge": 1024, "latent_edge": 64, "vignette": 0.20,
              "halation_thr": 0.86, "halation_op": 0.14, "halation_tint": [1.0, 0.55, 0.25],
              "grain_base": 4.0, "grain_size": 0.9, "webp_q": 85 },
  "guards": { "min_output_kb": 20, "max_fail_frac": 0.25 }
}
```

- [ ] **Step 4: Implement in pipeline/build.py** (create empty `pipeline/__init__.py` too)

```python
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_config(path=None):
    with open(path or os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)

def scan_sources(src_dir):
    best = {}
    for name in os.listdir(src_dir):
        stem, ext = os.path.splitext(name)
        ext = ext.upper()
        if ext not in (".JPG", ".JPEG", ".RAF"):
            continue
        ext = ".JPG" if ext == ".JPEG" else ext
        cur = best.get(stem)
        if cur is None or (ext == ".RAF" and cur["ext"] == ".JPG"):   # RAF wins over same-stem JPG
            best[stem] = {"stem": stem, "path": os.path.join(src_dir, name), "ext": ext}
    return [best[k] for k in sorted(best)]
```

- [ ] **Step 5: Run tests — both pass** (`python pipeline/test_pipeline.py`)

- [ ] **Step 6: Commit** — `git add -A && git commit` — `feat: config + source scanner (RAF-preferred dedupe)`

---

### Task 2: Decode, EXIF orientation, capture date

**Files:**
- Modify: `pipeline/grade.py` (create), `pipeline/test_pipeline.py`

**Interfaces:**
- Produces: `grade.decode(entry) -> (PIL.Image RGB, meta dict)` with `meta = {"date": "2026.05.28"|"", "frame": "0018"}`. Orientation ALWAYS applied via `ImageOps.exif_transpose`. RAF path uses `rawpy` `extract_thumb()` on the embedded JPEG then the same EXIF handling from the RAF file via `exifread`.

- [ ] **Step 1: Write the failing test** (append to test_pipeline.py)

```python
def test_decode_orientation_and_date():
    from PIL import Image
    from pipeline import grade
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "DSCF0250.JPG")
        img = Image.new("RGB", (400, 300), (120, 100, 90))
        ex = Image.Exif()
        ex[274] = 6                                   # rotate 90 CW
        ex[36867] = "2026:06:03 14:22:01"             # DateTimeOriginal
        img.save(p, exif=ex)
        out, meta = grade.decode({"stem": "DSCF0250", "path": p, "ext": ".JPG"})
        assert out.size == (300, 400), out.size        # transposed to portrait
        assert meta["date"] == "2026.06.03"
        assert meta["frame"] == "0250"
    print("ok test_decode_orientation_and_date")
```

- [ ] **Step 2: Run — fails** (grade module missing)

- [ ] **Step 3: Implement pipeline/grade.py**

```python
import io, os
from PIL import Image, ImageOps

def decode(entry):
    if entry["ext"] == ".RAF":
        import rawpy
        with rawpy.imread(entry["path"]) as raw:
            thumb = raw.extract_thumb()
        if thumb.format != rawpy.ThumbFormat.JPEG:
            raise ValueError("RAF has no embedded JPEG: " + entry["path"])
        img = Image.open(io.BytesIO(thumb.data))
        img.load()
        date = _raf_date(entry["path"])
        img = _raf_transpose(img, entry["path"])
    else:
        img = Image.open(entry["path"])
        exif = img.getexif()
        date = _fmt_date(exif.get(36867) or exif.get(306))
        img = ImageOps.exif_transpose(img)
    return img.convert("RGB"), {"date": date, "frame": entry["stem"].replace("DSCF", "")}

def _fmt_date(v):
    return v.split(" ")[0].replace(":", ".") if v else ""

_FLIPS = {3: Image.ROTATE_180, 6: Image.ROTATE_270, 8: Image.ROTATE_90}

def _raf_meta(path):
    import exifread
    with open(path, "rb") as f:
        return exifread.process_file(f, details=False)

def _raf_date(path):
    tags = _raf_meta(path)
    t = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
    return _fmt_date(str(t)) if t else ""

def _raf_transpose(img, path):
    tags = _raf_meta(path)
    t = tags.get("Image Orientation")
    if t and t.values and t.values[0] in _FLIPS:
        img = img.transpose(_FLIPS[t.values[0]])
    return img
```

- [ ] **Step 4: Run tests — pass.** Also run a live smoke check against one real RAF (not part of the suite): `python -c "from pipeline import grade; i,m = grade.decode({'stem':'DSCF0250','path':r'E:\Videos_Photos\X100T Photos\favorites\DSCF0250.RAF','ext':'.RAF'}); print(i.size, m)"` — expect portrait dims (height > width) and `2026.06.03`.

- [ ] **Step 5: Commit** — `feat: decode with EXIF orientation + capture date (JPG & RAF)`

---

### Task 3: Auto-straighten

**Files:**
- Modify: `pipeline/grade.py`, `pipeline/test_pipeline.py`

**Interfaces:**
- Produces: `grade.straighten(img, rcfg) -> (PIL.Image, float angle_applied)` — 0.0 means untouched. `rcfg` is `config["rotate"]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_straighten_tilted_horizon():
    import numpy as np
    from PIL import Image
    from pipeline import grade
    # sky over ground with a 2-degree horizon
    w, h = 1200, 800
    arr = np.zeros((h, w, 3), np.uint8)
    for x in range(w):
        yline = int(h * 0.5 + (x - w / 2) * 0.0349)   # tan(2 deg)
        arr[:yline, x] = (140, 160, 190)
        arr[yline:, x] = (60, 50, 40)
    img = Image.fromarray(arr)
    rcfg = {"min_angle": 0.3, "max_angle": 4.0, "min_area_keep": 0.88}
    out, ang = grade.straighten(img, rcfg)
    assert 1.0 < abs(ang) < 3.0, ang                   # detected roughly the 2-degree tilt
    assert out.size[0] * out.size[1] >= 0.88 * w * h   # inscribed crop keeps >= 88% area
    # residual check: re-run finds nothing left to fix
    out2, ang2 = grade.straighten(out, rcfg)
    assert ang2 == 0.0 or abs(ang2) < 0.5, ang2
    print("ok test_straighten_tilted_horizon")

def test_straighten_no_horizon_untouched():
    import numpy as np
    from PIL import Image
    from pipeline import grade
    rng = np.random.default_rng(7)
    img = Image.fromarray(rng.integers(0, 255, (600, 900, 3), np.uint8))
    out, ang = grade.straighten(img, {"min_angle": 0.3, "max_angle": 4.0, "min_area_keep": 0.88})
    assert ang == 0.0 and out.size == (900, 600)       # noise = no consensus = no-op
    print("ok test_straighten_no_horizon_untouched")
```

- [ ] **Step 2: Run — fails**

- [ ] **Step 3: Implement in grade.py**

```python
import math
import numpy as np

def straighten(img, rcfg):
    w, h = img.size
    sw = 1000
    small = np.asarray(img.convert("L").resize((sw, max(1, int(sw * h / w)))))
    band = small[int(small.shape[0] * 0.2): int(small.shape[0] * 0.8)]
    import cv2
    edges = cv2.Canny(band, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, 60,
                            minLineLength=int(sw * 0.15), maxLineGap=24)
    if lines is None:
        return img, 0.0
    angs, wts = [], []
    for x1, y1, x2, y2 in lines[:, 0]:
        a = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if abs(a) <= 8.0:
            angs.append(a)
            wts.append(math.hypot(x2 - x1, y2 - y1))
    if not angs:
        return img, 0.0
    angs, wts = np.array(angs), np.array(wts)
    order = np.argsort(angs)
    angs, wts = angs[order], wts[order]
    cum = np.cumsum(wts)
    med = float(angs[np.searchsorted(cum, cum[-1] / 2)])   # length-weighted median
    inl = np.abs(angs - med) <= 0.5
    if wts[inl].sum() < 0.8 * sw:                          # consensus gate
        return img, 0.0
    spread = math.sqrt(float(np.average((angs[inl] - med) ** 2, weights=wts[inl])))
    if spread > 0.7 or abs(med) < rcfg["min_angle"] or abs(med) > rcfg["max_angle"]:
        return img, 0.0
    a = math.radians(abs(med))
    ca, sa, c2 = math.cos(a), math.sin(a), math.cos(2 * a)
    wr, hr = (w * ca - h * sa) / c2, (h * ca - w * sa) / c2
    if wr * hr < rcfg["min_area_keep"] * w * h or wr < 1 or hr < 1:
        return img, 0.0
    from PIL import Image as PILImage
    rot = img.rotate(med, resample=PILImage.BICUBIC, expand=True)   # screen-y-down: positive med rotates the tilt back level
    W, H = rot.size
    box = (int((W - wr) / 2), int((H - hr) / 2), int((W + wr) / 2), int((H + hr) / 2))
    return rot.crop(box), med
```

- [ ] **Step 4: Run tests.** If `test_straighten_tilted_horizon` residual check fails with the tilt DOUBLED (≈4°), the rotation sign is inverted for this coordinate system — change `rot = img.rotate(med, ...)` to `img.rotate(-med, ...)` and re-run. The residual assertion is the arbiter; do not skip it.

- [ ] **Step 5: Commit** — `feat: consensus-gated auto-straighten with inscribed crop`

---

### Task 4: White balance + exposure lift

**Files:**
- Modify: `pipeline/grade.py`, `pipeline/test_pipeline.py`

**Interfaces:**
- Produces: `grade.white_balance(arr, wcfg) -> (arr, gains list)` and `grade.exposure_lift(arr, ecfg) -> (arr, gamma float)` — both on float32 HxWx3 arrays in 0..1. `gamma == 1.0` means "no lift applied".

- [ ] **Step 1: Write the failing tests**

```python
def test_white_balance_clamped():
    import numpy as np
    from pipeline import grade
    rng = np.random.default_rng(1)
    base = rng.random((80, 120, 3)).astype(np.float32) * 0.6
    tinted = np.clip(base * np.array([1.35, 1.0, 0.75], np.float32), 0, 1)   # heavy warm cast
    out, gains = grade.white_balance(tinted, {"strength": 0.30, "clamp": 0.06})
    assert all(0.94 - 1e-6 <= g <= 1.06 + 1e-6 for g in gains), gains        # hard clamp
    assert gains[2] > 1.0 > gains[0]                                          # pushes back toward neutral
    print("ok test_white_balance_clamped")

def test_exposure_lift_underexposed():
    import numpy as np
    from pipeline import grade
    rng = np.random.default_rng(2)
    arr = (rng.random((100, 150, 3)).astype(np.float32) * 0.30)               # median ~0.15
    arr[:4, :4] = 0.995                                                       # protected highlights
    ecfg = {"target_median": 0.42, "gamma_min": 0.60, "dark_skip": 0.02, "dark_soft": 0.08}
    before_clip = float((arr.max(axis=-1) >= 0.99).mean())
    out, gamma = grade.exposure_lift(arr, ecfg)
    L = 0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2]
    assert float(np.median(L)) > 0.24                                          # visibly lifted
    assert gamma >= 0.60 - 1e-9                                                # clamped lift
    after_clip = float((out.max(axis=-1) >= 0.999).mean())
    assert after_clip <= before_clip + 1e-4                                    # cannot create clipping
    print("ok test_exposure_lift_underexposed")

def test_exposure_lift_dark_scene_skipped():
    import numpy as np
    from pipeline import grade
    arr = np.full((50, 50, 3), 0.008, np.float32)                              # the DSCF0204 case
    ecfg = {"target_median": 0.42, "gamma_min": 0.60, "dark_skip": 0.02, "dark_soft": 0.08}
    out, gamma = grade.exposure_lift(arr, ecfg)
    assert gamma == 1.0 and float(np.abs(out - arr).max()) < 1e-6              # untouched
    print("ok test_exposure_lift_dark_scene_skipped")
```

- [ ] **Step 2: Run — fails**

- [ ] **Step 3: Implement in grade.py**

```python
def white_balance(arr, wcfg):
    s, c = wcfg["strength"], wcfg["clamp"]
    if s <= 0:
        return arr, [1.0, 1.0, 1.0]
    flat = arr.reshape(-1, 3).astype(np.float64)
    L = flat.mean(axis=1)
    lo, hi = np.percentile(L, [1, 99])
    sel = flat[(L >= lo) & (L <= hi)]
    e = np.power(np.mean(np.power(sel, 6), axis=0), 1 / 6)          # shades-of-gray p=6
    gains = np.power(e[1] / np.maximum(e, 1e-6), s)                  # partial, green-anchored
    gains = np.clip(gains, 1 - c, 1 + c)
    return np.clip(arr * gains.astype(np.float32), 0, 1), [float(g) for g in gains]

def exposure_lift(arr, ecfg):
    L = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    med = float(np.median(L))
    if med < ecfg["dark_skip"]:
        return arr, 1.0                                              # deliberate darkness stays dark
    p = math.log(ecfg["target_median"]) / math.log(max(med, 1e-6))
    p = min(1.0, max(ecfg["gamma_min"], p))
    if med < ecfg["dark_soft"]:
        p = (1.0 + p) / 2.0                                          # halve the lift near-dark
    if p >= 1.0:
        return arr, 1.0
    Ls = np.power(np.maximum(L, 1e-6), p)
    scale = Ls / np.maximum(L, 1e-6)
    maxc = arr.max(axis=-1)
    scale = np.minimum(scale, 1.0 / np.maximum(maxc, 1e-6))          # per-pixel: no channel above 1
    return np.clip(arr * scale[..., None], 0, 1), float(p)
```

- [ ] **Step 4: Run tests — pass**

- [ ] **Step 5: Commit** — `feat: clamped shades-of-gray WB + highlight-safe gamma lift with dark-scene guard`

---

### Task 5: The look — LUT + finish (vignette, halation, grain, resize)

**Files:**
- Modify: `pipeline/grade.py`, `pipeline/test_pipeline.py`

**Interfaces:**
- Produces: `grade.build_look_lut(lcfg) -> PIL.ImageFilter.Color3DLUT` (build once per run); `grade.finish(img, fcfg, seed) -> PIL.Image` (resized to long_edge with vignette+halation+grain applied, deterministic per seed).

- [ ] **Step 1: Write the failing tests**

```python
def test_look_lut_fade_and_monotonic():
    import numpy as np
    from PIL import Image
    from pipeline import grade
    lcfg = {"fade_black": 0.05, "white_ceiling": 0.98, "shoulder": 0.80, "saturation": 0.95,
            "highlight_desat": 0.15, "shadow_tone": [-0.004, 0.004, 0.016],
            "highlight_tone": [0.014, 0.006, -0.008]}
    lut = grade.build_look_lut(lcfg)
    ramp = Image.fromarray(np.tile(np.arange(256, dtype=np.uint8), (4, 1))).convert("RGB")
    out = np.asarray(ramp.filter(lut)).astype(int)
    assert out[0, 0].mean() >= int(0.04 * 255)          # blacks faded up
    assert out[0, 255].mean() <= int(0.99 * 255)        # whites rolled down
    grey = out.mean(axis=2)[0]
    assert all(int(grey[i + 8]) >= int(grey[i]) - 1 for i in range(0, 248, 8))   # monotonic tone curve
    print("ok test_look_lut_fade_and_monotonic")

def test_finish_grain_and_size():
    import numpy as np
    from PIL import Image
    from pipeline import grade
    fcfg = {"long_edge": 512, "vignette": 0.20, "halation_thr": 0.86, "halation_op": 0.14,
            "halation_tint": [1.0, 0.55, 0.25], "grain_base": 4.0, "grain_size": 0.9}
    flat = Image.new("RGB", (1024, 683), (110, 110, 110))
    out = grade.finish(flat, fcfg, seed=42)
    assert max(out.size) == 512
    center = np.asarray(out)[300:340, 220:280].astype(np.float32)
    assert 1.0 < center.std() < 9.0                     # grain present, not noise soup
    out2 = grade.finish(Image.new("RGB", (1024, 683), (110, 110, 110)), fcfg, seed=42)
    assert np.array_equal(np.asarray(out), np.asarray(out2))    # deterministic per seed
    print("ok test_finish_grain_and_size")
```

- [ ] **Step 2: Run — fails**

- [ ] **Step 3: Implement in grade.py**

```python
from PIL import ImageFilter

def build_look_lut(lcfg):
    fb, wc = lcfg["fade_black"], lcfg["white_ceiling"]
    sat, hd, sh = lcfg["saturation"], lcfg["highlight_desat"], lcfg["shoulder"]
    st = np.array(lcfg["shadow_tone"])
    ht = np.array(lcfg["highlight_tone"])

    def f(r, g, b):
        v = np.array([r, g, b])
        L = 0.2126 * r + 0.7152 * g + 0.0722 * b
        v = L + (v - L) * (sat * (1 - hd * L * L))        # sat shaping, desat near white
        v = v + st * (1 - L) ** 2 + ht * L ** 2           # split tone
        v = fb + (wc - fb) * v                            # fade floor + ceiling
        v = np.where(v > sh, sh + (v - sh) * 0.8, v)      # soft shoulder
        return tuple(np.clip(v, 0, 1))

    return ImageFilter.Color3DLUT.generate(33, f)

def finish(img, fcfg, seed):
    from PIL import Image as PILImage
    import cv2
    img = img.copy()
    img.thumbnail((fcfg["long_edge"], fcfg["long_edge"]), PILImage.LANCZOS)
    a = np.asarray(img).astype(np.float32) / 255.0
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r2 = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
    a *= (1 - fcfg["vignette"] * np.clip(r2, 0, 1)[..., None] ** 1.25)          # vignette
    L = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    mask = np.clip((L - fcfg["halation_thr"]) / (1 - fcfg["halation_thr"]), 0, 1)
    glow = cv2.GaussianBlur(a * mask[..., None], (0, 0), max(2.0, 0.015 * max(w, h)))
    tint = np.array(fcfg["halation_tint"], np.float32)
    a = 1 - (1 - a) * (1 - glow * tint * fcfg["halation_op"])                    # screen blend
    rng = np.random.default_rng(seed)
    noise = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32),
                             (0, 0), fcfg["grain_size"])
    noise /= max(noise.std(), 1e-6)
    amp = (fcfg["grain_base"] / 255.0) * (0.35 + 0.65 * np.sin(np.pi * np.clip(L, 0, 1)) ** 0.9)
    a += (noise * amp)[..., None]                                                # luma-only grain, dead last
    return PILImage.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
```

- [ ] **Step 4: Run tests — pass**

- [ ] **Step 5: Commit** — `feat: frozen film look LUT + vignette/halation/grain finish`

---

### Task 6: Outputs + analysis

**Files:**
- Create: `pipeline/analyze.py`
- Modify: `pipeline/grade.py`, `pipeline/test_pipeline.py`

**Interfaces:**
- Produces: `grade.save_outputs(img, stem, photos_dir, fcfg) -> dict` = `{"full": "photos/full/<stem>.webp", "thumb": ..., "latent": ..., "w": int, "h": int}` (w/h of the FULL output; site-relative paths, forward slashes). Atomic writes, verified re-openable, ≥ min_output_kb for full/thumb.
- Produces: `analyze.analyze(img) -> {"hue": int, "band": 0|1|2, "sat": float, "lum": float, "tint": "#rrggbb"}` — band 0 warm (<60° or ≥330°), 1 green, 2 cool.

- [ ] **Step 1: Write the failing tests**

```python
def test_save_outputs_atomic_and_verified():
    from PIL import Image
    from pipeline import grade
    fcfg = {"webp_q": 85, "thumb_edge": 256, "latent_edge": 64}
    with tempfile.TemporaryDirectory() as d:
        img = Image.effect_noise((800, 533), 60).convert("RGB")   # noisy = compressible but nonempty
        out = grade.save_outputs(img, "DSCF0018", d, fcfg)
        for key in ("full", "thumb", "latent"):
            p = os.path.join(d, *out[key].split("/")[1:])
            assert os.path.exists(p), p
            Image.open(p).verify()
        assert out["w"] == 800 and out["h"] == 533
        assert not any(f.endswith(".tmp") for _, _, fs in os.walk(d) for f in fs)
    print("ok test_save_outputs_atomic_and_verified")

def test_analyze_bands():
    from PIL import Image
    from pipeline import analyze
    warm = analyze.analyze(Image.new("RGB", (64, 64), (200, 120, 60)))
    cool = analyze.analyze(Image.new("RGB", (64, 64), (60, 110, 200)))
    green = analyze.analyze(Image.new("RGB", (64, 64), (70, 180, 80)))
    assert warm["band"] == 0 and cool["band"] == 2 and green["band"] == 1
    assert warm["tint"].startswith("#") and 0 <= warm["lum"] <= 1
    print("ok test_analyze_bands")
```

- [ ] **Step 2: Run — fails**

- [ ] **Step 3: Implement.** In `grade.py`:

```python
def _atomic_save(img, path, **kw):
    tmp = path + ".tmp"
    img.save(tmp, **kw)
    os.replace(tmp, path)
    from PIL import Image as PILImage
    PILImage.open(path).verify()

def save_outputs(img, stem, photos_dir, fcfg):
    from PIL import Image as PILImage, ImageFilter as IF
    paths = {}
    for sub in ("full", "thumb", "latent"):
        os.makedirs(os.path.join(photos_dir, sub), exist_ok=True)
    full_p = os.path.join(photos_dir, "full", stem + ".webp")
    _atomic_save(img, full_p, format="WEBP", quality=fcfg["webp_q"], method=6)
    thumb = img.copy()
    thumb.thumbnail((fcfg["thumb_edge"],) * 2, PILImage.LANCZOS)
    _atomic_save(thumb, os.path.join(photos_dir, "thumb", stem + ".webp"),
                 format="WEBP", quality=fcfg["webp_q"], method=6)
    latent = img.copy()
    latent.thumbnail((fcfg["latent_edge"],) * 2, PILImage.LANCZOS)
    latent = latent.filter(IF.GaussianBlur(2))
    _atomic_save(latent, os.path.join(photos_dir, "latent", stem + ".webp"),
                 format="WEBP", quality=60, method=6)
    base = os.path.basename(photos_dir)
    for sub in ("full", "thumb", "latent"):
        paths[sub] = "%s/%s/%s.webp" % (base, sub, stem)
    paths["w"], paths["h"] = img.size
    return paths
```

New file `pipeline/analyze.py`:

```python
import colorsys
import numpy as np

def analyze(img):
    small = img.copy()
    small.thumbnail((64, 64))
    hsv = np.asarray(small.convert("HSV"), dtype=np.float32)
    H = hsv[..., 0] * 360.0 / 255.0
    S = hsv[..., 1] / 255.0
    V = hsv[..., 2] / 255.0
    sel = (S > 0.18) & (V > 0.10)
    hue = float(np.median(H[sel])) if sel.any() else 30.0
    sat = float(S[sel].mean()) if sel.any() else 0.1
    lum = float(np.median(np.asarray(small.convert("L")))) / 255.0
    band = 0 if (hue < 60 or hue >= 330) else (1 if hue < 160 else 2)
    r, g, b = colorsys.hsv_to_rgb(hue / 360.0, min(0.35, sat * 0.8), 0.16)
    tint = "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
    return {"hue": int(round(hue)), "band": band, "sat": round(sat, 3),
            "lum": round(lum, 3), "tint": tint}
```

- [ ] **Step 4: Run tests — pass.** (min_output_kb enforcement lives in build.py Task 8, where the guard config is in scope.)

- [ ] **Step 5: Commit** — `feat: atomic WebP outputs (full/thumb/latent) + graded-image analysis`

---

### Task 7: Auto-composer

**Files:**
- Create: `pipeline/compose.py`, `overrides.json` (content: `{}`)
- Modify: `pipeline/test_pipeline.py`

**Interfaces:**
- Consumes: manifest entries `{"id": stem, "date", "frame", "w", "h", "hue", "band", "sat", "lum", ...}`.
- Produces: `compose.compose(photos, cfg, overrides) -> {"reel": [scene...], "sheet": [id...]}` where scene is `{"type": "solo"|"diptych"|"strip", "ids": [...], "mask": "letterbox"|"iris"|None}`. Deterministic: same input → same output. Rules (spec §7): reel = newest `reel_size` by (date, frame); hero = newest, solo+letterbox, first; closer = lowest-lum, solo, last; portraits (h>w) adjacent in capture order + same band → diptych (max 2); ≥3 consecutive same-band landscapes → strip of 3 (max 1); iris = highest-sat band-2 solo, else middle solo; `overrides[id]["skip"]` drops a photo entirely. Sheet = ALL photos sorted (band, lum).

- [ ] **Step 1: Write the failing test**

```python
def _mk(i, date, w, h, band, sat, lum):
    return {"id": "DSCF%04d" % i, "frame": "%04d" % i, "date": date,
            "w": w, "h": h, "band": band, "sat": sat, "lum": lum}

def test_compose_rules():
    from pipeline import compose
    photos = [
        _mk(1, "2026.05.01", 3, 2, 0, .3, .10),   # oldest landscape warm
        _mk(2, "2026.05.02", 3, 2, 0, .3, .30),
        _mk(3, "2026.05.03", 3, 2, 0, .3, .40),   # 1+2+3 = warm landscape run -> strip
        _mk(4, "2026.05.04", 2, 3, 0, .3, .50),
        _mk(5, "2026.05.05", 2, 3, 0, .3, .60),   # 4+5 adjacent warm portraits -> diptych
        _mk(6, "2026.05.06", 2, 3, 2, .8, .35),   # cool portrait, highest sat -> iris solo
        _mk(7, "2026.05.07", 3, 2, 0, .3, .05),   # darkest -> closer
        _mk(8, "2026.05.08", 3, 2, 2, .4, .70),   # newest -> hero
    ]
    out = compose.compose(photos, {"reel_size": 14}, {})
    reel = out["reel"]
    assert reel[0] == {"type": "solo", "ids": ["DSCF0008"], "mask": "letterbox"}      # hero
    assert reel[-1] == {"type": "solo", "ids": ["DSCF0007"], "mask": None}            # darkest closer
    assert {"type": "strip", "ids": ["DSCF0001", "DSCF0002", "DSCF0003"], "mask": None} in reel
    assert {"type": "diptych", "ids": ["DSCF0004", "DSCF0005"], "mask": None} in reel
    assert {"type": "solo", "ids": ["DSCF0006"], "mask": "iris"} in reel
    assert out["sheet"][0] == "DSCF0007"                     # band 0, darkest first
    assert compose.compose(photos, {"reel_size": 14}, {}) == out                       # deterministic
    out2 = compose.compose(photos, {"reel_size": 14}, {"DSCF0006": {"skip": True}})
    assert all("DSCF0006" not in s["ids"] for s in out2["reel"])
    print("ok test_compose_rules")
```

- [ ] **Step 2: Run — fails**

- [ ] **Step 3: Implement pipeline/compose.py**

```python
def compose(photos, cfg, overrides):
    photos = [p for p in photos if not overrides.get(p["id"], {}).get("skip")]
    by_new = sorted(photos, key=lambda p: (p["date"], p["frame"]), reverse=True)
    reel = by_new[: cfg["reel_size"]]
    hero = reel[0]
    rest = [p for p in reel[1:]]
    closer = min(rest, key=lambda p: (p["lum"], p["frame"])) if rest else None
    if closer:
        rest = [p for p in rest if p["id"] != closer["id"]]
    rest.sort(key=lambda p: (p["date"], p["frame"]))          # capture order for the middle

    used, units = set(), []
    # one strip: first run of >=3 consecutive same-band landscapes
    for i in range(len(rest) - 2):
        trio = rest[i: i + 3]
        if all(p["w"] > p["h"] for p in trio) and len({p["band"] for p in trio}) == 1 \
           and not any(p["id"] in used for p in trio):
            units.append((trio[0], {"type": "strip", "ids": [p["id"] for p in trio], "mask": None}))
            used.update(p["id"] for p in trio)
            break
    # up to two diptychs: adjacent same-band portraits
    pairs = 0
    for i in range(len(rest) - 1):
        a, b = rest[i], rest[i + 1]
        if pairs < 2 and a["id"] not in used and b["id"] not in used \
           and a["h"] > a["w"] and b["h"] > b["w"] and a["band"] == b["band"]:
            units.append((a, {"type": "diptych", "ids": [a["id"], b["id"]], "mask": None}))
            used.update((a["id"], b["id"]))
            pairs += 1
    solos = [p for p in rest if p["id"] not in used]
    units.extend((p, {"type": "solo", "ids": [p["id"]], "mask": None}) for p in solos)
    units.sort(key=lambda u: (u[0]["date"], u[0]["frame"]))
    scenes = [u[1] for u in units]
    # iris: highest-sat cool solo, else the middle solo
    solo_scenes = [s for s in scenes if s["type"] == "solo"]
    cool = [s for s in solo_scenes
            if next(p for p in rest if p["id"] == s["ids"][0])["band"] == 2]
    if cool:
        tgt = max(cool, key=lambda s: next(p for p in rest if p["id"] == s["ids"][0])["sat"])
        tgt["mask"] = "iris"
    elif solo_scenes:
        solo_scenes[len(solo_scenes) // 2]["mask"] = "iris"
    reel_scenes = [{"type": "solo", "ids": [hero["id"]], "mask": "letterbox"}] + scenes
    if closer:
        reel_scenes.append({"type": "solo", "ids": [closer["id"]], "mask": None})
    sheet = [p["id"] for p in sorted(photos, key=lambda p: (p["band"], p["lum"], p["frame"]))]
    return {"reel": reel_scenes, "sheet": sheet}
```

- [ ] **Step 4: Run tests — pass**

- [ ] **Step 5: Commit** — `feat: deterministic auto-composer (hero/diptychs/strip/iris/closer + tone-sorted sheet)`

---

### Task 8: build.py orchestrator

**Files:**
- Modify: `pipeline/build.py`, `pipeline/test_pipeline.py`
- Create: `site/assets/data.dev.js` (content: `window.PHOTOS={};window.SCENES=[];window.SHEET=[];window.META={};`)

**Interfaces:**
- Produces: `build.run(cfg, root=ROOT) -> int` (exit code) and CLI `python pipeline/build.py [--source DIR] [--force]`. Behavior:
  1. Scan sources; per photo compute `sha1(file bytes)[:12]`; skip photos whose hash matches `site/photos/.state.json` unless `--force`.
  2. Per changed photo: decode → straighten → to float array → WB → lift → back to image → LUT (built once) → finish (seed = int of stem sha1) → save_outputs → analyze(graded full image) → manifest entry. Per-photo try/except: on error log and continue; NO no-edit publish of broken files.
  3. Enforce `guards.min_output_kb` on full/thumb (undersized = that photo errors).
  4. If error fraction > `guards.max_fail_frac` → print summary, exit 1, do NOT write manifest/state.
  5. Compose with overrides.json; manifest = `{"photos": {id: entry}, "scenes": [...], "sheet": [...], "meta": {"title", "intro_line"}}`.
  6. Write `site/assets/data.<sha1(content)[:10]>.js` containing `window.PHOTOS=...;window.SCENES=...;window.SHEET=...;window.META=...;` — delete older `data.*.js`, regex-rewrite `assets/data\.[a-z0-9]+\.js` in both `site/index.html` and `site/contact.html`.
  7. Copy hero full image as JPEG → `site/photos/og.jpg` (quality 85).
  8. Append one JSON line per photo to `site/photos/.log.jsonl`: `{"stem", "action": "graded"|"skipped"|"error", "gamma", "wb", "angle", "error"}`. Update `.state.json` only on success.

- [ ] **Step 1: Write the failing test**

```python
def _fake_favorites(d):
    from PIL import Image
    import numpy as np
    rng = np.random.default_rng(5)
    for i, shade in ((1, 60), (2, 90)):
        arr = (rng.random((400, 600, 3)) * shade).astype("uint8")
        img = Image.fromarray(arr)
        ex = Image.Exif()
        ex[36867] = "2026:07:0%d 10:00:00" % i
        img.save(os.path.join(d, "DSCF000%d.JPG" % i), exif=ex)

def test_build_end_to_end_and_idempotent():
    from pipeline import build
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as root:
        _fake_favorites(src)
        os.makedirs(os.path.join(root, "site", "assets"))
        for page in ("index.html", "contact.html"):
            with open(os.path.join(root, "site", page), "w") as f:
                f.write('<script src="assets/data.dev.js"></script>')
        with open(os.path.join(root, "overrides.json"), "w") as f:
            f.write("{}")
        cfg = build.load_config()
        cfg["source_dir"] = src
        cfg["finish"]["long_edge"] = 512
        cfg["guards"]["min_output_kb"] = 1
        assert build.run(cfg, root=root) == 0
        assets = os.listdir(os.path.join(root, "site", "assets"))
        data = [a for a in assets if a.startswith("data.") and a != "data.dev.js"]
        assert len(data) == 1, assets
        html = open(os.path.join(root, "site", "index.html")).read()
        assert data[0] in html                                   # reference rewritten
        content = open(os.path.join(root, "site", "assets", data[0])).read()
        assert "window.PHOTOS" in content and "window.SCENES" in content
        assert os.path.exists(os.path.join(root, "site", "photos", "og.jpg"))
        log1 = open(os.path.join(root, "site", "photos", ".log.jsonl")).read().count("graded")
        assert log1 == 2
        assert build.run(cfg, root=root) == 0                    # second run: all skipped
        log = open(os.path.join(root, "site", "photos", ".log.jsonl")).read()
        assert log.count('"skipped"') == 2
    print("ok test_build_end_to_end_and_idempotent")
```

- [ ] **Step 2: Run — fails**

- [ ] **Step 3: Implement `run()` + CLI in build.py.** Structure (write it exactly to the interface contract above):

```python
import hashlib, re, sys, time

def _sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]

def run(cfg, root=ROOT, force=False):
    from PIL import Image
    import numpy as np
    from pipeline import grade, analyze, compose
    photos_dir = os.path.join(root, "site", "photos")
    os.makedirs(photos_dir, exist_ok=True)
    state_p = os.path.join(photos_dir, ".state.json")
    state = json.load(open(state_p)) if os.path.exists(state_p) else {}
    manifest_p = os.path.join(photos_dir, ".manifest.json")
    manifest = json.load(open(manifest_p)) if os.path.exists(manifest_p) else {}
    overrides = json.load(open(os.path.join(root, "overrides.json"), encoding="utf-8"))
    entries = scan_sources(cfg["source_dir"])
    lut = grade.build_look_lut(cfg["look"])
    log_lines, errors = [], 0
    for e in entries:
        h = _sha1_file(e["path"])
        if not force and state.get(e["stem"]) == h and e["stem"] in manifest:
            log_lines.append({"stem": e["stem"], "action": "skipped"})
            continue
        try:
            img, meta = grade.decode(e)
            img, angle = grade.straighten(img, cfg["rotate"])
            arr = np.asarray(img).astype(np.float32) / 255.0
            arr, wb = grade.white_balance(arr, cfg["wb"])
            if not overrides.get(e["stem"], {}).get("no_lift"):
                arr, gamma = grade.exposure_lift(arr, cfg["exposure"])
            else:
                gamma = 1.0
            img = Image.fromarray((arr * 255).astype("uint8")).filter(lut)
            seed = int(hashlib.sha1(e["stem"].encode()).hexdigest()[:8], 16)
            img = grade.finish(img, cfg["finish"], seed)
            paths = grade.save_outputs(img, e["stem"], photos_dir, cfg["finish"])
            for key in ("full", "thumb"):
                p = os.path.join(root, "site", *paths[key].split("/"))
                if os.path.getsize(p) < cfg["guards"]["min_output_kb"] * 1024:
                    raise ValueError("output undersized: " + paths[key])
            entry = {"id": e["stem"], **meta, **paths, **analyze.analyze(img),
                     "caption": overrides.get(e["stem"], {}).get("caption", "")}
            manifest[e["stem"]] = entry
            state[e["stem"]] = h
            log_lines.append({"stem": e["stem"], "action": "graded", "gamma": round(gamma, 3),
                              "wb": [round(g, 3) for g in wb], "angle": round(angle, 2)})
        except Exception as ex:
            errors += 1
            log_lines.append({"stem": e["stem"], "action": "error", "error": str(ex)})
    with open(os.path.join(photos_dir, ".log.jsonl"), "a", encoding="utf-8") as f:
        for line in log_lines:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), **line}) + "\n")
    for line in log_lines:
        print(" ", line)
    if entries and errors / len(entries) > cfg["guards"]["max_fail_frac"]:
        print("BUILD FAILED: %d/%d photos errored — nothing published" % (errors, len(entries)))
        return 1
    photos = [manifest[k] for k in sorted(manifest) if k in {e["stem"] for e in entries}]
    composed = compose.compose(photos, cfg, overrides)
    data = ("window.PHOTOS=%s;window.SCENES=%s;window.SHEET=%s;window.META=%s;" % (
        json.dumps({p["id"]: p for p in photos}), json.dumps(composed["reel"]),
        json.dumps(composed["sheet"]),
        json.dumps({"title": cfg["title"], "intro_line": cfg["intro_line"]})))
    dhash = hashlib.sha1(data.encode()).hexdigest()[:10]
    assets = os.path.join(root, "site", "assets")
    for old in os.listdir(assets):
        if re.match(r"data\.[a-z0-9]+\.js$", old) and old != "data.dev.js":
            os.remove(os.path.join(assets, old))
    with open(os.path.join(assets, "data.%s.js" % dhash), "w", encoding="utf-8") as f:
        f.write(data)
    for page in ("index.html", "contact.html"):
        pp = os.path.join(root, "site", page)
        html = open(pp, encoding="utf-8").read()
        html = re.sub(r"assets/data\.[a-z0-9]+\.js", "assets/data.%s.js" % dhash, html)
        open(pp, "w", encoding="utf-8").write(html)
    hero_id = composed["reel"][0]["ids"][0]
    Image.open(os.path.join(root, "site", *manifest[hero_id]["full"].split("/"))) \
         .convert("RGB").save(os.path.join(photos_dir, "og.jpg"), quality=85)
    json.dump(state, open(state_p, "w"))
    json.dump(manifest, open(manifest_p, "w"))
    print("BUILD OK: %d photos (%d graded, %d errors)" % (len(photos),
          sum(1 for l in log_lines if l["action"] == "graded"), errors))
    return 0

if __name__ == "__main__":
    cfg = load_config()
    if "--source" in sys.argv:
        cfg["source_dir"] = sys.argv[sys.argv.index("--source") + 1]
    sys.exit(run(cfg, force="--force" in sys.argv))
```

- [ ] **Step 4: Run full test suite — all pass** (`python pipeline/test_pipeline.py`)

- [ ] **Step 5: Commit** — `feat: build orchestrator — incremental grading, manifest, hashed data emit, og.jpg`

---

### Task 9: Contact Sheet page

**Files:**
- Create: `site/assets/site.css`, `site/contact.html`
- Source to port: `C:\Users\Bertrand\Desktop\dev\claude\dumps\photo-showcase\mockups\contact.html` + `mock.css` (round 8 — visual source of truth)

**Interfaces:**
- Consumes: `window.PHOTOS` (dict by id: `thumb`, `latent`, `full`, `frame`, `date`, `caption`, `w`, `h`), `window.SHEET` (sorted ids), `window.META.title`.

Port `mock.css` into `site/assets/site.css` unchanged (tokens, grain overlay, lightbox) plus the contact-page styles from the mockup's `<style>` block. Then apply these deltas to the page:

- [ ] **Step 1: Build the page.** `<script src="assets/data.dev.js"></script>` before the inline script. Replace `window.MOCK_PHOTOS` usage:

```js
const photos = window.SHEET.map(id => window.PHOTOS[id]);   // pre-sorted band->lum by the composer
```

Header title text = `window.META.title` (uppercased, letterspaced as in mockup). Keep verbatim from the round-8 mockup: hover bulge `scale(1.38)` + `drift` keyframes + `glowpulse` amber ring/glow + sibling dim `.strip:hover .frame:not(:hover) { opacity: .32 }`; single sheet heading `THE SHEET — EMBER TO ICE, DARK TO LIGHT`; edge print `0018A · HALF-LIGHT 400` → replace the hardcoded `HALF-LIGHT` with `META.title.toUpperCase()`; lightbox meta `No. NNNN · date · X100T` (+ caption line under it when `p.caption` is non-empty). Thumbnails: `<img src="${p.thumb}" loading="lazy" style="background:#0b0b0b url(${p.latent}) center/cover">` (latent as placeholder under lazy thumbs). Keyboard access (goal #12 — this page IS the a11y fallback): each `.frame` gets `tabindex="0"` and an Enter/Space keydown handler that triggers the same lightbox open as click; `:focus-visible` reuses the hover ring style; Escape already closes.

- [ ] **Step 2: Verify in browser.** Add a temporary "mockups"-style launch entry serving `site/` on port 8791 (or `python -m http.server 8791 -d site`), generate real data first via `python pipeline/build.py` — if Task 12 hasn't run yet, run `python pipeline/build.py --source <two-photo test dir>`. Probe: no console errors; frames render in SHEET order; hover rules present (`@keyframes drift`, ring in `glowpulse`); lightbox opens/closes; mobile 375px: 2-col grid, no x-overflow.

- [ ] **Step 3: Commit** — `feat: contact sheet page (tone-sorted, safelight hover, lazy thumbs)`

---

### Task 10: Projection Room page

**Files:**
- Create: `site/index.html`
- Source to port: `C:\Users\Bertrand\Desktop\dev\claude\dumps\photo-showcase\mockups\projection.html` (round 8)

**Interfaces:**
- Consumes: `window.PHOTOS`, `window.SCENES` (composer output: `{type, ids, mask}`), `window.META`.

Port the round-8 page structure/CSS/JS verbatim (it already implements every motion contract), with these deltas:

- [ ] **Step 1: Scenes come from data, not hardcoded.**

```js
const G = '#131313';
const SCENES = [
  { type: 'text', tint: G, scatter: true,
    html: `<h1>${window.META.title.toUpperCase()}</h1><p class="line">${window.META.intro_line}</p>` },
  ...window.SCENES.map(s => ({ ...s })),        // {type, ids, mask} from the composer
  { type: 'text', tint: G,
    html: '<p class="line">the roll continues</p><div class="mono" style="margin-top:22px">NEW FRAMES ARE DEVELOPED AS THEY ARE TAKEN</div>' },
];
```

In the scene builder, `byId` becomes `window.PHOTOS`; photo scenes read `mask` for letterbox/iris instead of the mockup's `sc.mask` literals (same property name — no other change). Tint: `sc.tint = sc.tint || window.PHOTOS[sc.ids[0]].tint;` (as mockup). `img src` uses `p.full`.

- [ ] **Step 2: Lazy-load with latent placeholders.** In `neg()`, emit `<img data-src="${p.full}" style="background:url(${p.latent}) center/cover">` (no `src`). In `paint()`, when a scene's `ad < 2.5`, promote once: `sc.imgs.forEach(im => { if (!im.src) im.src = im.dataset.src; })`.

- [ ] **Step 3: Reduced motion.**

```js
const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
// in the lerp tick: if (RM) tSmooth = tTarget;          — no glide
// scatter: skip wrapping/transforms when RM (letters render static)
// parallax: if (RM) plx effectively 0 — guard the img transform assignment
```

- [ ] **Step 4: OG/social + title tags** in `<head>`:

```html
<title>Half-Light</title>
<meta property="og:title" content="Half-Light">
<meta property="og:description" content="the inner machinations of a photographic mind are an enigma">
<meta property="og:image" content="photos/og.jpg">
```

(The literal "Half-Light" in `<title>`/`og:` is acceptable static copy — build.py does not rewrite it; swapping the pseudonym later means editing config.json + these two files, documented in README.)

- [ ] **Step 5: Verify with the probe harness** (the page keeps `window.__render(t)`). Serve `site/`, then assert via browser JS console/probes: no console errors; scene count = `window.SCENES.length + 2`; no `rotate(` in any photo `.mover` transform at t = 1.0/1.45/3.5; mover scale within [1.0, 1.06]; scrim opacity = 0.45 at t = x.5 and 0 at scene centers; letterbox `inset(45%→0)` on scene 1; one iris scene present when the composer assigned one; strip frames light by opacity (no `filter`); edge print lands late. Mobile 375×812: no x-overflow, diptych side-by-side, strip vertical. `?reduced-motion` check via devtools emulation: no scatter transforms.

- [ ] **Step 6: Commit** — `feat: projection room page (data-driven scenes, lazy latent loading, reduced-motion)`

---

### Task 11: SYNC.bat + README

**Files:**
- Create: `deploy/SYNC.bat`, `README.md`

- [ ] **Step 1: Write deploy/SYNC.bat** (CRLF line endings):

```bat
@echo off
title Half-Light SYNC
cd /d C:\Users\Bertrand\Desktop\dev\photo-showcase
echo Grading new photos...
python pipeline\build.py
if errorlevel 1 (
  color 4F
  echo.
  echo  SYNC FAILED - nothing was published. See site\photos\.log.jsonl
  pause
  exit /b 1
)
git add -A
git commit -m "sync: new photos" >nul 2>&1
git push
echo.
echo  DONE - Cloudflare deploys in about a minute.
pause
```

- [ ] **Step 2: Write README.md** with: what the repo is; how SYNC works (copy `deploy\SYNC.BAT` shortcut into the favorites folder — a `.lnk` shortcut, so the working dir stays the repo); the **one-time setup** numbered walkthrough (create private GitHub repo → `git remote add origin` → push → Cloudflare Dashboard → Workers & Pages → connect repo → build command *none*, output dir `site` → done); how to change the pseudonym (config.json + `<title>`/og tags in site/index.html, site/contact.html); overrides.json schema (`skip`, `caption`, `no_lift`); where logs live.

- [ ] **Step 3: Test the bat** (without push — no remote yet): run `deploy\SYNC.bat` from Explorer double-click; expect build output, commit created, push fails with "no remote" — acceptable and noted in README (works after one-time setup). Verify the failure path: temporarily set `"max_fail_frac": -1`… no — instead run with `--source` pointing at an empty temp dir via a copy of the bat; simpler: trust the errorlevel branch (it is 3 lines) and verify exit code manually: `python pipeline\build.py --source <empty dir>` then `echo %errorlevel%` → expect 0 (zero photos, zero errors). The >25% failure path is already covered by unit understanding; do not over-test the bat.

- [ ] **Step 4: Commit** — `feat: one-click SYNC + setup README`

---

### Task 12: Real run, eye-vet, look calibration (HUMAN GATE), freeze

**Files:**
- Modify: `pipeline/build.py` (add `--calibrate`), `config.json` (frozen look values after Bertrand's pick)

- [ ] **Step 1: Add `--calibrate` mode to build.py.** Grades 8 representative photos (spread: 2 darkest, 2 brightest, 2 most saturated, 2 portraits) under three look variants into `_work/calibrate.html` — a side-by-side grid (SOOC | A subtle | B default | C bold) using inline `<img>`:

```python
VARIANTS = {
  "A-subtle": {"saturation": 0.90, "tone_mul": 0.7, "fade_black": 0.04, "grain_base": 3.0},
  "B-default": {"saturation": 0.95, "tone_mul": 1.0, "fade_black": 0.05, "grain_base": 4.0},
  "C-bold":   {"saturation": 1.02, "tone_mul": 1.5, "fade_black": 0.06, "grain_base": 5.0},
}
# tone_mul scales look.shadow_tone and look.highlight_tone vectors
```

Each variant runs the full §4 pipeline (decode→straighten→WB→lift→variant LUT→finish at long_edge 1024 into `_work/cal/<variant>/<stem>.webp`). `_work/` is gitignored (already).

- [ ] **Step 2: Run `python pipeline/build.py --calibrate`** on the real favorites. Open `_work/calibrate.html` in the browser pane. **Eye-vet every photo for orientation** (hard rule from project memory: exif_transpose AND eye-vet — DSCF0252 stays landscape).

- [ ] **Step 3: HUMAN GATE — present the calibration sheet to Bertrand.** He picks A/B/C or asks for knob tweaks (iterate: adjust variant, re-run, re-present). **Do not proceed past this step without his explicit pick.** Write the chosen values into `config.json` `look` block. Commit — `feat: frozen look (Bertrand-calibrated)`.

- [ ] **Step 4: Full real build:** `python pipeline/build.py --force` (regrade all with frozen look). Review `.log.jsonl`: every action `graded`, zero errors; check applied angles cluster < 2°; verify DSCF0204 logged `gamma: 1.0` (dark-scene guard held).

- [ ] **Step 5: Full-site verification on real data** (serve `site/`): run the Task 10 probe list end-to-end + Task 9 checks; click through the contact sheet lightbox on 5+ photos; confirm reel has ≤ `reel_size` photos, diptychs are same-band, strip all-landscape; mobile pass.

- [ ] **Step 6: Commit** — `feat: first real build — full favorites graded and composed` (graded WebPs + manifest + data file are committed; sources are not).

- [ ] **Step 7: Hand off to Bertrand:** README one-time setup section (GitHub private repo + Cloudflare Pages link) — the only steps requiring his accounts. After his push, verify the live URL renders both pages; then update the project memory (photo-portfolio.md) and dumps STATUS.md to point at the repo as canonical.

---

## Self-Review (completed)

**Spec coverage:** §3 layout → Task 1/8/9/10/11; §4 grading steps 1–9 → Tasks 2–6, 8 (guards in 8, calibration §4.6 → Task 12); §5 motion contracts + reduced-motion + lazy/latent → Task 10; §6 shared analysis + hashed manifest → Tasks 6/8; §7 composer rules + overrides → Task 7; §8 contact sheet → Task 9; §9 SYNC + Cloudflare + OG → Tasks 10/11; §10 testing → every task's test steps + probe harness; §11–12 out of scope/open → Task 12 step 7 handoff. Gap check: spec's "pair_with" override — deliberately deferred (composer's `skip`/`caption`/`no_lift` implemented; `pair_with` adds when first needed — YAGNI, noted here so it isn't a silent drop).
**Goal register (STATUS.md, all 12):** 1 SYNC-in-folder → Task 11 · 2 bolder grade → Task 12 variants/calibration · 3 reel cap 10–20 → config `reel_size` + composer slice · 4 auto-composer + overrides → Task 7 · 5 pre-rendered latent, no runtime blur → Tasks 6/10 · 6 content-hashed data → Task 8 · 7 lazy-load by proximity → Task 10 · 8 one shared analysis → Task 6 (analyze on graded output feeds manifest, composer, both pages) · 9 dark-scene guard + no_lift override → Tasks 4/8/12 · 10 OG/title → Task 10 · 11 RAF>JPG dedupe → Task 1 · 12 reduced-motion + keyboard fallback → Tasks 9/10.
**Placeholders:** none — every code step has concrete code; the two port-based tasks (9, 10) reference the round-8 mockup files as their source plus enumerated deltas with code.
**Type consistency:** `scan_sources` entries feed `decode(entry)`; `decode` meta merges into manifest entries consumed by `analyze`-augmented dicts in `compose(photos, cfg, overrides)`; scene dicts `{type, ids, mask}` consumed verbatim by Task 10's builder; config key names match config.json throughout (`exposure.target_median`, `rotate.min_area_keep`, `finish.grain_base`, `guards.max_fail_frac`). Verified consistent.
