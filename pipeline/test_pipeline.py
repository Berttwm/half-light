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
    assert cfg["exposure"]["target_median"] == 0.47
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

    # LOOK V3: full regime param set at its bright-regime extreme (facade-like) must
    # still hold a monotonic tone curve — mid_lift/warm boosts are the new risk here.
    # ROUND 3e ceiling: warm_sat_mult 2.4 raw (golden coefficient's full permitted bound
    # 1.4 at golden_s=1) — the realized-boost cap (2.0) applies inside build_look_lut
    # itself, so this exercises that cap path at its ceiling, not just build.py's
    # actually-chosen coefficient. mid_lift ceiling unchanged (0.06). ROUND 3f adds
    # pink_sat_mult at its own regime-formula max (1 + PASTEL_SAT_COEF*pastel_s=1, i.e.
    # 1.15) — shares the exact same capped-boost code path as warm_sat_mult, which is
    # already stress-tested above, so no need to also push this one to the cap.
    v3 = {**lcfg, "mid_lift": 0.06, "warm_sat_mult": 2.4, "warm_lum_add": 0.09,
          "cool_sat_mult": 0.96, "toe_depth": 0.045, "toe_end": 0.25, "shoulder": 0.72,
          "pink_sat_mult": 1.15}
    out_v3 = np.asarray(ramp.filter(grade.build_look_lut(v3))).astype(int)
    grey_v3 = out_v3.mean(axis=2)[0]
    assert all(int(grey_v3[i + 8]) >= int(grey_v3[i]) - 1 for i in range(0, 248, 8))
    print("ok test_look_lut_fade_and_monotonic")

def test_look_lut_toe_darkens_shadows():
    import numpy as np
    from PIL import Image
    from pipeline import grade
    base = {"fade_black": 0.0, "white_ceiling": 1.0, "shoulder": 0.95, "saturation": 1.0,
            "highlight_desat": 0.0, "shadow_tone": [0, 0, 0], "highlight_tone": [0, 0, 0]}
    flat = Image.new("RGB", (4, 4), (20, 20, 20))                              # mid-low shadow, L ~ 0.078
    out0 = np.asarray(flat.filter(grade.build_look_lut(base))).astype(int)
    out1 = np.asarray(flat.filter(grade.build_look_lut({**base, "toe_depth": 0.05, "toe_end": 0.25}))).astype(int)
    assert out1.mean() < out0.mean() - 3            # toe visibly darkens a mid-shadow value vs toe_depth 0
    print("ok test_look_lut_toe_darkens_shadows")

def test_look_lut_vibrance_self_limits():
    import colorsys
    import numpy as np
    from PIL import Image
    from pipeline import grade
    base = {"fade_black": 0.0, "white_ceiling": 1.0, "shoulder": 0.95, "saturation": 1.0,
            "highlight_desat": 0.0, "shadow_tone": [0, 0, 0], "highlight_tone": [0, 0, 0]}
    def chroma_ratio(rgb):
        # ROUND 3d: self-limiting is a property of the boost FACTOR, not the resulting
        # absolute chroma delta — two colors sharing a hue but differing only in chroma
        # isolate it cleanly (an absolute-delta comparison across *different* hues
        # conflates the chroma gate with the warm bell's own hue weighting, which the
        # 3d re-centered bell broke: hue~10deg now gets much more bell weight than it
        # used to, so the old two-different-hue fixture's absolute gains flipped order
        # even though the underlying self-limiting factor is unchanged and correct).
        px = Image.new("RGB", (2, 2), tuple(int(round(c * 255)) for c in rgb))
        def chroma(lut):
            a = np.asarray(px.filter(lut)).astype(np.float32)[0, 0]
            return float(a.max() - a.min())
        return chroma(grade.build_look_lut({**base, "warm_sat_mult": 1.5})) / chroma(grade.build_look_lut(base))
    hue = 22 / 360                                     # same warm hue for both — isolates the chroma gate
    muted = colorsys.hsv_to_rgb(hue, 0.15, 0.55)        # low-chroma warm/skin-like entry
    saturated = colorsys.hsv_to_rgb(hue, 0.65, 0.75)    # already-saturated warm entry, same hue
    muted_ratio = chroma_ratio(muted)
    saturated_ratio = chroma_ratio(saturated)
    assert muted_ratio > saturated_ratio > 1.0          # self-limiting: muted warm entry gains more than saturated one
    print("ok test_look_lut_vibrance_self_limits")

def _mk_regime_arr(L, warm_frac, warm_s=0.5):
    """Synthetic 100x100 array with an exact median luminance L: every pixel
    shares that same weighted luma, so mixing a warm-hued fraction with a
    perfectly gray fraction can't shift the median off target. warm_s controls
    the warm pixels' own HSV saturation (hence their measured warm chroma) —
    WAVE 2 addition, needed to test the closed-loop golden boost's muted-vs-
    vivid distinction (default 0.5 keeps every pre-WAVE-2 call site identical)."""
    import colorsys
    import numpy as np
    r, g, b = colorsys.hsv_to_rgb(32 / 360, warm_s, 1.0)        # hue 32deg (bell peak)
    k = L / (0.2126 * r + 0.7152 * g + 0.0722 * b)              # scale preserves hue & S, hits L exactly
    warm = np.array([r * k, g * k, b * k], np.float32)
    n = 100 * 100
    arr = np.tile(np.array([L, L, L], np.float32), (n, 1))
    arr[: int(n * warm_frac)] = warm
    return arr.reshape(100, 100, 3)

def test_regime_params():
    from pipeline import build
    cfg = {"look": {"toe_dark": 0.008, "toe_bright": 0.045, "look_strength": 1.0,
                     "target_warm_chroma": 0.30}}

    dark_look, _ = build._regime_look(cfg, _mk_regime_arr(0.06, 0.05))       # 0022/0018-like
    assert abs(dark_look["warm_sat_mult"] - 1.0) < 0.02, dark_look
    assert abs(dark_look["cool_sat_mult"] - 0.85) < 0.02, dark_look
    assert abs(dark_look["pink_sat_mult"] - 1.0) < 0.02, dark_look          # no pastel signal, no pink push

    # WAVE 2 / complaint A — THE key new invariant (the client's literal ask): the old
    # open-loop formula boosted purely by regime signature (bright + warm-hued), so a
    # facade-like scene always got the same big multiplier regardless of how vivid its
    # warm areas already were — that's what over-saturated DSCF9170/9155/9292/9593 etc.
    # Same regime signature (med .42 = golden_bell peak, warm_frac .6 = gate maxed) but
    # differing only in the warm pixels' own chroma, split into two cases:
    muted_look, muted_log = build._regime_look(cfg, _mk_regime_arr(0.42, 0.6, warm_s=0.3))
    assert muted_log["warm_chroma"] < cfg["look"]["target_warm_chroma"], muted_log
    assert muted_look["warm_sat_mult"] >= 1.3, muted_look        # muted: boosted clearly > 1
    assert muted_look["warm_lum_add"] > 0, muted_look            # muted: gets the luminance glow

    vivid_look, vivid_log = build._regime_look(cfg, _mk_regime_arr(0.42, 0.6, warm_s=0.75))
    assert vivid_log["warm_chroma"] >= cfg["look"]["target_warm_chroma"], vivid_log
    assert vivid_look["warm_sat_mult"] <= 1.02, vivid_look       # already-vivid: no pile-on
    assert vivid_look["warm_lum_add"] == 0, vivid_look           # already-rich: no added glow

    # ROUND 3e/3f: pastel-regime design intent is "lift luminance, KEEP chroma" — the
    # pastel term (untouched by WAVE 2, out of complaint A's scope) still dominates here.
    sky_look, _ = build._regime_look(cfg, _mk_regime_arr(0.66, 0.6))         # 0252-like
    assert sky_look["warm_sat_mult"] > 1.0, sky_look
    assert sky_look["pink_sat_mult"] > 1.0, sky_look
    print("ok test_regime_params")

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

def test_finish_zero_effects_are_noop():
    import numpy as np
    from PIL import Image
    from pipeline import grade
    fcfg = {"long_edge": 512, "vignette": 0.0, "halation_thr": 0.86, "halation_op": 0.0,
            "halation_tint": [1.0, 0.55, 0.25], "grain_base": 0.0, "grain_size": 0.9}
    flat = Image.new("RGB", (1024, 683), (110, 110, 110))
    out = grade.finish(flat, fcfg, seed=42)
    center = np.asarray(out)[300:340, 220:280].astype(np.float32)
    assert center.std() < 0.5                       # grain_base 0 -> zero flat-patch noise
    print("ok test_finish_zero_effects_are_noop")

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

def _mk(i, date, w, h, band, sat, lum, hue=0):
    return {"id": "DSCF%04d" % i, "frame": "%04d" % i, "date": date,
            "w": w, "h": h, "band": band, "sat": sat, "lum": lum, "hue": hue}

def test_compose_rules():
    from pipeline import compose
    photos = [
        _mk(1, "2026.05.01", 3, 2, 0, .3, .10),   # oldest landscape warm
        _mk(2, "2026.05.02", 3, 2, 0, .3, .30),
        _mk(3, "2026.05.03", 3, 2, 0, .3, .40),   # 1+2+3 = warm landscape run -> falls through to solos (strip removed, WAVE 2)
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
    assert not any(s["type"] == "strip" for s in reel)                               # strip scene type removed entirely
    assert {"type": "solo", "ids": ["DSCF0001"], "mask": None} in reel               # landscape run -> individual solos
    assert {"type": "solo", "ids": ["DSCF0002"], "mask": None} in reel
    assert {"type": "solo", "ids": ["DSCF0003"], "mask": None} in reel
    assert {"type": "diptych", "ids": ["DSCF0004", "DSCF0005"], "mask": None} in reel
    assert {"type": "solo", "ids": ["DSCF0006"], "mask": "iris"} in reel
    assert out["sheet"] == ["DSCF0007", "DSCF0001", "DSCF0002", "DSCF0003",
                            "DSCF0004", "DSCF0005", "DSCF0006", "DSCF0008"]  # night rack, then serpentine
    assert compose.compose(photos, {"reel_size": 14}, {}) == out                       # deterministic
    out2 = compose.compose(photos, {"reel_size": 14}, {"DSCF0006": {"skip": True}})
    assert all("DSCF0006" not in s["ids"] for s in out2["reel"])
    print("ok test_compose_rules")

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

def test_compose_diptych_hue_pairing_nonadjacent():
    from pipeline import compose
    photos = [
        _mk(1, "2026.05.01", 2, 3, 0, .3, .40, hue=10),    # A
        _mk(2, "2026.05.02", 2, 3, 0, .3, .45, hue=170),   # B
        _mk(3, "2026.05.03", 2, 3, 0, .3, .50, hue=12),    # C -> nearest hue to A, non-adjacent
        _mk(4, "2026.05.04", 2, 3, 0, .3, .55, hue=200),   # D -> nearest remaining, pairs with B
        _mk(5, "2026.05.05", 3, 2, 0, .3, .05),            # darkest landscape -> closer
        _mk(6, "2026.05.06", 3, 2, 0, .3, .90),            # newest landscape -> hero
    ]
    out = compose.compose(photos, {"reel_size": 14}, {})
    reel = out["reel"]
    # adjacency-based pairing would give (1,2)+(3,4); nearest-hue gives these instead
    assert {"type": "diptych", "ids": ["DSCF0001", "DSCF0003"], "mask": None} in reel
    assert {"type": "diptych", "ids": ["DSCF0002", "DSCF0004"], "mask": None} in reel
    assert compose.compose(photos, {"reel_size": 14}, {}) == out               # deterministic
    print("ok test_compose_diptych_hue_pairing_nonadjacent")

def test_compose_empty_inputs():
    from pipeline import compose
    assert compose.compose([], {"reel_size": 14}, {}) == {"reel": [], "sheet": []}
    photos = [_mk(1, "2026.05.01", 3, 2, 0, .3, .10)]
    out = compose.compose(photos, {"reel_size": 14}, {"DSCF0001": {"skip": True}})
    assert out == {"reel": [], "sheet": []}
    print("ok test_compose_empty_inputs")

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

def test_cli_entry_importable():
    import subprocess, sys as s
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as scratch:
        os.makedirs(os.path.join(scratch, "site", "assets"))
        for page in ("index.html", "contact.html"):
            with open(os.path.join(scratch, "site", page), "w") as f:
                f.write('<script src="assets/data.dev.js"></script>')
        with open(os.path.join(scratch, "overrides.json"), "w") as f:
            f.write("{}")
        r = subprocess.run([s.executable, os.path.join("pipeline", "build.py"), "--source", src, "--root", scratch],
                           cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    assert r.returncode == 0, r.stdout.decode()[-500:]
    print("ok test_cli_entry_importable")

def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    main()
