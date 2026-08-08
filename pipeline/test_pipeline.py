import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import build, grade

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

def test_decode_orientation_and_date():
    from PIL import Image
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

def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    main()
