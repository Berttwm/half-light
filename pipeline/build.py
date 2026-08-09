import hashlib, json, math, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ponytail: calibration is a one-shot human-in-the-loop dev tool, not a shipped
# feature — no tests added for it by design (see task-12 brief step 1).
# LOOK V3 (round 3): empirically-fitted regime layer replaces the old dose
# variants entirely — one grade per photo, adapted to its own brightness/hue
# content instead of a human picking soft/med/strong.

REGIME_KEYS = ("toe_depth", "mid_lift", "warm_sat_mult", "warm_lum_add", "cool_sat_mult", "shoulder")
# ROUND 3b: mid_lift's bright-regime anchor (0.045) is shared by every bright photo, not
# just pastel ones — a flat bump to 0.06 also nudged DSCF0212 (bright, non-pastel) further
# past its own median-L target. Gated the extra 0.015 (0.045->0.06 total) to pastel_s
# instead, so golden-but-not-pastel scenes like 0212 are untouched (pastel_s=0 there).
MID_LIFT_PASTEL_BONUS = 0.015

def _clamp01(x):
    return max(0.0, min(1.0, x))

def _lerp(a, b, t):
    return a + (b - a) * t

def _measure_regime(arr):
    """med_L (median luma), warm_frac (share of pixels in the warm hue band with
    real saturation) on a 96px thumb of a post-lift array. Shared by run() and
    calibrate() so both grade identically."""
    from PIL import Image
    import numpy as np
    from pipeline import grade
    small = Image.fromarray((np.clip(arr, 0, 1) * 255).astype("uint8"))
    small.thumbnail((96, 96))
    a = np.asarray(small, dtype=np.float32) / 255.0
    L = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    maxc, minc = a.max(axis=-1), a.min(axis=-1)
    S = np.where(maxc > 0, (maxc - minc) / np.maximum(maxc, 1e-6), 0.0)
    hue = grade.hue_deg(a[..., 0], a[..., 1], a[..., 2])
    warm = (hue >= 5) & (hue <= 70) & (S > 0.15)
    return float(np.median(L)), float(warm.mean()), float(S.mean())

def _regime_look(cfg, arr):
    """LOOK V3 regime layer: derives per-photo toe/mid/warm-cool LUT params from
    the photo's own measured brightness and warm-hue content (client-fitted
    formula, see task-12-report ROUND 3). Returns (look_dict, log_dict).
    `look_strength` scales the regime *signal* (bright/golden/pastel) before it
    feeds the lerps — at 0 every photo grades at the dark-regime baseline."""
    med_L, warm_frac, _scene_sat = _measure_regime(arr)
    lk = cfg["look"]
    ls = lk.get("look_strength", 1.0)
    bright = _clamp01((med_L - 0.15) / 0.30)
    golden_gate = _clamp01((warm_frac - 0.12) / 0.35)
    # ROUND 3d: golden bell narrowed (sigma 0.15->0.12, med .66 contribution 0.278->0.135)
    # and pastel steepened (was clamp((med_L-0.55)/0.15,0,1)) to free the coefficient bound
    # for the facade push without also inflating skylight/pastel scenes.
    golden_bell = math.exp(-((med_L - 0.42) ** 2) / (2 * 0.12 ** 2))
    pastel = _clamp01((med_L - 0.52) / 0.10)
    bright_s = bright * ls
    golden_s = golden_bell * golden_gate * ls
    pastel_s = pastel * golden_gate * ls

    params = {
        "toe_depth": round(_lerp(lk["toe_dark"], lk["toe_bright"], bright_s), 3),
        "mid_lift": round(_lerp(0.010, 0.045, bright_s) + MID_LIFT_PASTEL_BONUS * pastel_s, 3),
        # ROUND 3d: golden coefficient bound extended to [0.38, 1.2]. Diagnostic sweep
        # (see report) found the realized warm ratio asymptotes at ~0.858 as raw
        # warm_sat_mult -> infinity — the 1.75 cap and 0.7 gate slope (kept as-is per
        # this round's brief) structurally bound it below the 0.88 target regardless of
        # coefficient. Took 1.2 (top of range) anyway: unlike ROUND 3b/3c, going to the
        # bound here costs nothing — 0022/0018/0252 all stay flat-to-improved and the
        # narrowed golden_bell sigma + steepened pastel keep 0252 and the skylight D-test
        # point comfortably non-boosted even at 1.2 (verified below), so there's no
        # tradeoff left to protect by holding back.
        "warm_sat_mult": round(1 + 1.2 * golden_s - 0.28 * pastel_s, 3),
        "warm_lum_add": round(0.09 * golden_s + 0.04 * pastel_s, 3),
        "cool_sat_mult": round(_lerp(0.85, 0.96, bright_s), 3),
        "shoulder": round(_lerp(0.80, 0.72, bright_s), 3),
    }
    look = dict(lk, **params)
    regime_log = {"med": round(med_L, 3), "bright": round(bright, 3),
                  "golden": round(golden_bell * golden_gate, 3), "pastel": round(pastel, 3)}
    return look, regime_log

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

def _sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]

# client's own reference grades exist for these — always in the calibration sheet
FORCED_CALIBRATION_STEMS = ["DSCF0018", "DSCF0022", "DSCF0212", "DSCF0252"]

def select_calibration_stems(manifest):
    """4 forced client-reference stems + 4 more spread across lum/sat/orientation
    extremes, deduped by walking down each ranking so overlaps don't shrink the
    set below 8."""
    entries = list(manifest.values())
    picked = set()
    picks = []
    for stem in FORCED_CALIBRATION_STEMS:
        e = manifest.get(stem)
        if e is None or stem in picked:
            continue
        picked.add(stem)
        picks.append((stem, "client reference (lum=%.3f sat=%.3f %dx%d)" %
                      (e["lum"], e["sat"], e["w"], e["h"])))
    def take(ranked, label, n):
        got = []
        for rank, e in enumerate(ranked, 1):
            if e["id"] in picked:
                continue
            picked.add(e["id"])
            got.append((e["id"], "%s #%d (lum=%.3f sat=%.3f %dx%d)" %
                        (label, rank, e["lum"], e["sat"], e["w"], e["h"])))
            if len(got) == n:
                break
        return got
    picks += take(sorted(entries, key=lambda e: (e["lum"], e["id"])), "darkest", 1)
    picks += take(sorted(entries, key=lambda e: (-e["sat"], e["id"])), "most saturated", 1)
    picks += take(sorted([e for e in entries if e["h"] > e["w"]], key=lambda e: e["id"]), "portrait", 1)
    picks += take(sorted(entries, key=lambda e: (-e["lum"], e["id"])), "brightest", 1)
    return picks

# client's own reference edits (identification verified by controller) —
# refs live as siblings of source_dir: <X100T Photos>/refs/photo_N_*.jpg
REF_MAP = {"photo_1": "DSCF0212", "photo_2": "DSCF0022", "photo_3": "DSCF0018", "photo_4": "DSCF0252"}

def _fit_stats(ours, ref):
    """Simple fit check between our V3 grade and the client's reference edit:
    median-luma delta and warm/cool-bin saturation ratios, both measured the
    same way as the regime layer itself so the numbers are comparable."""
    import numpy as np
    from pipeline import grade
    def stats(img):
        small = img.convert("RGB").copy()
        small.thumbnail((256, 256))
        a = np.asarray(small, dtype=np.float32) / 255.0
        L = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
        maxc, minc = a.max(axis=-1), a.min(axis=-1)
        S = np.where(maxc > 0, (maxc - minc) / np.maximum(maxc, 1e-6), 0.0)
        hue = grade.hue_deg(a[..., 0], a[..., 1], a[..., 2])
        warm, cool = (hue >= 5) & (hue <= 70), (hue >= 95) & (hue <= 235)
        return (float(np.median(L)), float(S[warm].mean()) if warm.any() else 0.0,
                float(S[cool].mean()) if cool.any() else 0.0)
    med_o, warm_o, cool_o = stats(ours)
    med_r, warm_r, cool_r = stats(ref)
    return {"med_L_delta": round(med_o - med_r, 3),
            "warm_sat_ratio": round(warm_o / warm_r, 3) if warm_r > 1e-6 else None,
            "cool_sat_ratio": round(cool_o / cool_r, 3) if cool_r > 1e-6 else None}

CAL_EXT = {"sooc": "webp", "v3": "webp", "ref": "jpg"}   # ref is a straight copy of the client's own jpg

def _calibrate_html(picks, ref_stems, fits):
    rows = []
    for stem, reason in picks:
        cols = ["sooc", "v3"] + (["ref"] if stem in ref_stems else [])
        cells = "".join('<div class="cell"><img src="cal/%s/%s.%s" loading="lazy"></div>' % (c, stem, CAL_EXT[c])
                         for c in cols)
        fit_html = ""
        if stem in fits:
            f = fits[stem]
            fit_html = ('<div class="fit">fit vs ref — median L delta %+.3f  '
                        'warm sat ratio %s  cool sat ratio %s</div>' %
                        (f["med_L_delta"], f["warm_sat_ratio"], f["cool_sat_ratio"]))
        rows.append('<div class="stem">%s — %s</div><div class="row cols%d">%s</div>%s' %
                     (stem, reason, len(cols), cells, fit_html))
    return """<!doctype html><meta charset="utf-8"><title>calibration</title>
<style>
body{background:#131313;color:#ddd;font-family:monospace;margin:0;padding:24px}
.legend{text-transform:uppercase;letter-spacing:.08em;color:#888;font-size:12px;margin-bottom:8px}
.row{display:grid;gap:8px}
.cols2{grid-template-columns:repeat(2,1fr)}
.cols3{grid-template-columns:repeat(3,1fr)}
.cell img{width:100%%;display:block}
.stem{margin:28px 0 6px;color:#777;font-size:13px}
.fit{color:#6a6;font-size:12px;margin-top:4px}
</style>
<div class="legend">sooc / half-light v3 / your edit (client refs only)</div>
%s
""" % "\n".join(rows)

def calibrate(cfg, root=ROOT):
    import glob, shutil
    from PIL import Image
    import numpy as np
    from pipeline import grade
    photos_dir = os.path.join(root, "site", "photos")
    manifest = json.load(open(os.path.join(photos_dir, ".manifest.json"), encoding="utf-8"))
    overrides = json.load(open(os.path.join(root, "overrides.json"), encoding="utf-8"))
    sources = {e["stem"]: e for e in scan_sources(cfg["source_dir"])}
    picks = select_calibration_stems(manifest)
    ref_by_stem = {}
    refs_dir = os.path.join(os.path.dirname(cfg["source_dir"]), "refs")
    if os.path.isdir(refs_dir):
        for photo_id, stem in REF_MAP.items():
            hits = glob.glob(os.path.join(refs_dir, photo_id + "_*"))
            if hits:
                ref_by_stem[stem] = hits[0]

    work = os.path.join(root, "_work")
    cal = os.path.join(work, "cal")
    for sub in ("sooc", "v3", "ref"):
        os.makedirs(os.path.join(cal, sub), exist_ok=True)

    fits = {}
    for stem, reason in picks:
        entry = sources[stem]
        img, _meta = grade.decode(entry)
        img, _angle = grade.straighten(img, cfg["rotate"])       # shared geometry, not "grade"

        sooc = img.copy()
        sooc.thumbnail((1024, 1024), Image.LANCZOS)
        sooc.save(os.path.join(cal, "sooc", stem + ".webp"), format="WEBP", quality=85, method=6)

        arr = np.asarray(img).astype(np.float32) / 255.0
        arr, _wb = grade.white_balance(arr, cfg["wb"])
        seed = int(hashlib.sha1(stem.encode()).hexdigest()[:8], 16)
        if not overrides.get(stem, {}).get("no_lift"):
            arr, _gamma = grade.exposure_lift(arr, cfg["exposure"])
        look, regime_log = _regime_look(cfg, arr)
        graded = Image.fromarray((arr * 255).astype("uint8")).filter(grade.build_look_lut(look))
        fcfg = dict(cfg["finish"], long_edge=1024, grain_base=0.0)   # client formula: no grain
        graded = grade.finish(graded, fcfg, seed)
        graded.save(os.path.join(cal, "v3", stem + ".webp"), format="WEBP", quality=85, method=6)

        ref_path = ref_by_stem.get(stem)
        if ref_path:
            shutil.copy(ref_path, os.path.join(cal, "ref", stem + ".jpg"))
            fits[stem] = _fit_stats(graded, Image.open(ref_path))
        print("  calibrated", stem, "-", reason, "-", regime_log)

    html = _calibrate_html(picks, set(ref_by_stem), fits)
    with open(os.path.join(work, "calibrate.html"), "w", encoding="utf-8") as f:
        f.write(html)
    for src in re.findall(r'src="([^"]+)"', html):        # every <img> must resolve on disk
        if not os.path.exists(os.path.join(work, src)):
            print("WARNING: calibrate.html references missing file:", src)
    if fits:
        print("FIT vs client reference edits (our V3 vs his edit):")
        for stem in REF_MAP.values():
            if stem in fits:
                f = fits[stem]
                print("  %s  median L delta %+.3f  warm sat ratio %s  cool sat ratio %s" %
                      (stem, f["med_L_delta"], f["warm_sat_ratio"], f["cool_sat_ratio"]))
    print("CALIBRATE OK: %d photos -> _work/calibrate.html" % len(picks))
    return 0

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
    luts = {}   # one LUT per regime param tuple, built lazily and cached for the run
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
            look, regime_log = _regime_look(cfg, arr)
            lut_key = tuple(look[k] for k in REGIME_KEYS)
            if lut_key not in luts:
                luts[lut_key] = grade.build_look_lut(look)
            img = Image.fromarray((arr * 255).astype("uint8")).filter(luts[lut_key])
            seed = int(hashlib.sha1(e["stem"].encode()).hexdigest()[:8], 16)
            img = grade.finish(img, cfg["finish"], seed)
            paths = grade.save_outputs(img, e["stem"], photos_dir, cfg["finish"])
            for key in ("full",):  # thumbs/latents derive from the verified full; dark photos legitimately compress tiny
                p = os.path.join(root, "site", *paths[key].split("/"))
                if os.path.getsize(p) < cfg["guards"]["min_output_kb"] * 1024:
                    raise ValueError("output undersized: " + paths[key])
            entry = {"id": e["stem"], **meta, **paths, **analyze.analyze(img),
                     "caption": overrides.get(e["stem"], {}).get("caption", "")}
            manifest[e["stem"]] = entry
            state[e["stem"]] = h
            log_lines.append({"stem": e["stem"], "action": "graded", "gamma": round(gamma, 3),
                              "wb": [round(g, 3) for g in wb], "angle": round(angle, 2),
                              "regime": regime_log})
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
    if composed["reel"]:                                # zero-photo builds still succeed (no hero)
        hero_id = composed["reel"][0]["ids"][0]
        Image.open(os.path.join(root, "site", *manifest[hero_id]["full"].split("/"))) \
             .convert("RGB").save(os.path.join(photos_dir, "og.jpg"), quality=85)
    json.dump(state, open(state_p, "w"))
    json.dump(manifest, open(manifest_p, "w"))
    print("BUILD OK: %d photos (%d graded, %d errors)" % (len(photos),
          sum(1 for l in log_lines if l["action"] == "graded"), errors))
    return 0

if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    cfg = load_config()
    root = ROOT
    if "--source" in sys.argv:
        cfg["source_dir"] = sys.argv[sys.argv.index("--source") + 1]
    if "--root" in sys.argv:
        root = sys.argv[sys.argv.index("--root") + 1]
    if "--calibrate" in sys.argv:
        sys.exit(calibrate(cfg, root=root))
    sys.exit(run(cfg, root=root, force="--force" in sys.argv))
