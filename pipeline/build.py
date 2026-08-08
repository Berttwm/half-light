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
