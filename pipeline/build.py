import hashlib, json, os, re, sys, time

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
    if "--source" in sys.argv:
        cfg["source_dir"] = sys.argv[sys.argv.index("--source") + 1]
    sys.exit(run(cfg, force="--force" in sys.argv))
