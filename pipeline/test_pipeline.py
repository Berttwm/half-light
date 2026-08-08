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

def test_straighten_single_short_line_untouched():
    import numpy as np
    from PIL import Image
    from pipeline import grade
    arr = np.full((600, 900, 3), 128, np.uint8)
    for x in range(300, 550):                          # one short 3-degree edge, nothing else
        y = int(300 + (x - 425) * 0.0524)
        arr[y:y+3, x] = 20
    out, ang = grade.straighten(Image.fromarray(arr), {"min_angle": 0.3, "max_angle": 4.0, "min_area_keep": 0.88})
    assert ang == 0.0 and out.size == (900, 600), ang
    print("ok test_straighten_single_short_line_untouched")

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

def test_exposure_lift_saturated_no_pileup():
    import numpy as np
    from pipeline import grade
    arr = np.full((40, 40, 3), 0.12, np.float32)
    arr[:, :, 2] = 0.5                                 # saturated blue: maxc 0.5, luminance ~0.07
    ecfg = {"target_median": 0.42, "gamma_min": 0.60, "dark_skip": 0.02, "dark_soft": 0.08}
    out, gamma = grade.exposure_lift(arr, ecfg)
    assert float(out[..., 2].max()) <= 0.985           # soft shoulder: never slams the ceiling
    assert float(out[..., 2].min()) >= 0.5 - 1e-6      # lift-only: blue channel not darkened
    print("ok test_exposure_lift_saturated_no_pileup")

def test_exposure_lift_dark_scene_skipped():
    import numpy as np
    from pipeline import grade
    arr = np.full((50, 50, 3), 0.008, np.float32)                              # the DSCF0204 case
    ecfg = {"target_median": 0.42, "gamma_min": 0.60, "dark_skip": 0.02, "dark_soft": 0.08}
    out, gamma = grade.exposure_lift(arr, ecfg)
    assert gamma == 1.0 and float(np.abs(out - arr).max()) < 1e-6              # untouched
    print("ok test_exposure_lift_dark_scene_skipped")

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

def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    main()
