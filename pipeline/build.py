import hashlib, json, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ponytail: calibration is a one-shot human-in-the-loop dev tool, not a shipped
# feature — no tests added for it by design (see task-12 brief step 1).
# LOOK V2 (round 2): axis is exposure/toe/adaptive-sat/shoulder strength, not
# the old saturation/tone_mul/grain axis — client rejected the film-fade look.
VARIANTS = {
    "L-soft":   {"exposure_target": 0.45, "toe_depth": 0.02,  "sat_adaptive_max": 0.10, "shoulder": 0.75},
    "L-med":    {"exposure_target": 0.47, "toe_depth": 0.03,  "sat_adaptive_max": 0.14, "shoulder": 0.72},
    "L-strong": {"exposure_target": 0.50, "toe_depth": 0.045, "sat_adaptive_max": 0.20, "shoulder": 0.68},
}

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

def _sat_bucket(arr):
    """4-level adaptive-saturation bucket (0-3) from mean HSV S of a 64px thumb
    of the current (post exposure-lift) array. Shared by run() and calibrate()
    so both apply identical bucketing."""
    from PIL import Image
    import numpy as np
    small = Image.fromarray((np.clip(arr, 0, 1) * 255).astype("uint8"))
    small.thumbnail((64, 64))
    s_mean = float(np.asarray(small.convert("HSV"), dtype=np.float32)[..., 1].mean()) / 255.0
    return min(3, int(s_mean / 0.12))

def _calibrate_html(picks, variants):
    cols = ["sooc"] + list(variants)
    rows = []
    for stem, reason in picks:
        cells = "".join('<div class="cell"><img src="cal/%s/%s.webp" loading="lazy"></div>' % (c, stem)
                         for c in cols)
        rows.append('<div class="stem">%s — %s</div><div class="row">%s</div>' % (stem, reason, cells))
    head = "".join('<div class="h">%s</div>' % c for c in cols)
    return """<!doctype html><meta charset="utf-8"><title>calibration</title>
<style>
body{background:#131313;color:#ddd;font-family:monospace;margin:0;padding:24px}
.head,.row{display:grid;grid-template-columns:repeat(%d,1fr);gap:8px}
.head{position:sticky;top:0;background:#131313;padding:8px 0;text-transform:uppercase;
      letter-spacing:.08em;color:#888;font-size:12px}
.cell img{width:100%%;display:block}
.stem{margin:28px 0 6px;color:#777;font-size:13px}
</style>
<div class="head">%s</div>
%s
""" % (len(cols), head, "\n".join(rows))

def calibrate(cfg, root=ROOT):
    from PIL import Image
    import numpy as np
    from pipeline import grade
    photos_dir = os.path.join(root, "site", "photos")
    manifest = json.load(open(os.path.join(photos_dir, ".manifest.json"), encoding="utf-8"))
    overrides = json.load(open(os.path.join(root, "overrides.json"), encoding="utf-8"))
    sources = {e["stem"]: e for e in scan_sources(cfg["source_dir"])}
    picks = select_calibration_stems(manifest)

    work = os.path.join(root, "_work")
    cal = os.path.join(work, "cal")
    for sub in ["sooc"] + list(VARIANTS):
        os.makedirs(os.path.join(cal, sub), exist_ok=True)

    for stem, reason in picks:
        entry = sources[stem]
        img, _meta = grade.decode(entry)
        img, _angle = grade.straighten(img, cfg["rotate"])       # shared geometry, not "grade"

        sooc = img.copy()
        sooc.thumbnail((1024, 1024), Image.LANCZOS)
        sooc.save(os.path.join(cal, "sooc", stem + ".webp"), format="WEBP", quality=85, method=6)

        base_arr = np.asarray(img).astype(np.float32) / 255.0
        base_arr, _wb = grade.white_balance(base_arr, cfg["wb"])
        seed = int(hashlib.sha1(stem.encode()).hexdigest()[:8], 16)

        # each variant carries its own exposure_target, so lift (and the
        # sat bucket it feeds) is recomputed per variant, not shared.
        for name, v in VARIANTS.items():
            arr = base_arr
            if not overrides.get(stem, {}).get("no_lift"):
                ecfg = {**cfg["exposure"], "target_median": v["exposure_target"]}
                arr, _gamma = grade.exposure_lift(arr, ecfg)
            b = _sat_bucket(arr)                                   # same bucketing as the real build
            look = {**cfg["look"], "toe_depth": v["toe_depth"], "shoulder": v["shoulder"],
                    "sat_boost": v["sat_adaptive_max"] * b / 3}
            graded = Image.fromarray((arr * 255).astype("uint8")).filter(grade.build_look_lut(look))
            fcfg = dict(cfg["finish"], long_edge=1024, grain_base=0.0)   # client formula: no grain
            graded = grade.finish(graded, fcfg, seed)
            graded.save(os.path.join(cal, name, stem + ".webp"), format="WEBP", quality=85, method=6)
        print("  calibrated", stem, "-", reason)

    with open(os.path.join(work, "calibrate.html"), "w", encoding="utf-8") as f:
        f.write(_calibrate_html(picks, VARIANTS))
    print("CALIBRATE OK: %d photos x %d variants -> _work/calibrate.html" % (len(picks), len(VARIANTS)))
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
    luts = {}   # one LUT per adaptive-sat bucket, built lazily and cached for the run
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
            sat_bucket = _sat_bucket(arr)
            if sat_bucket not in luts:
                sat_boost = cfg["look"].get("sat_adaptive_max", 0.0) * sat_bucket / 3
                luts[sat_bucket] = grade.build_look_lut({**cfg["look"], "sat_boost": sat_boost})
            img = Image.fromarray((arr * 255).astype("uint8")).filter(luts[sat_bucket])
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
                              "sat_bucket": sat_bucket})
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
