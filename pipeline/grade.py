import io
import math
import os
import numpy as np
from PIL import Image, ImageOps, ImageFilter

def decode(entry):
    if entry["ext"] == ".RAF":
        import rawpy
        with rawpy.imread(entry["path"]) as raw:
            thumb = raw.extract_thumb()
        if thumb.format != rawpy.ThumbFormat.JPEG:
            raise ValueError("RAF has no embedded JPEG: " + entry["path"])
        img = Image.open(io.BytesIO(thumb.data))
        img.load()
    else:
        img = Image.open(entry["path"])

    # Extract EXIF and date from embedded image (JPG or embedded JPEG in RAF)
    exif = img.getexif()
    date = _fmt_date(exif.get(36867) or exif.get(306))

    # Fall back to RAF exifread only if embedded EXIF lacks date
    if not date and entry["ext"] == ".RAF":
        date = _raf_date(entry["path"])

    img = ImageOps.exif_transpose(img)

    return img.convert("RGB"), {"date": date, "frame": entry["stem"].replace("DSCF", "")}

def _fmt_date(v):
    return v.split(" ")[0].replace(":", ".") if v else ""

def _raf_meta(path):
    import exifread
    with open(path, "rb") as f:
        return exifread.process_file(f, details=False)

def _raf_date(path):
    tags = _raf_meta(path)
    t = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
    return _fmt_date(str(t)) if t else ""

def straighten(img, rcfg):
    import cv2
    w, h = img.size
    sw = 1000
    small = np.asarray(img.convert("L").resize((sw, max(1, int(sw * h / w)))))
    band = small[int(small.shape[0] * 0.2): int(small.shape[0] * 0.8)]
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
    ABS_FLOOR = 0.6 * sw
    if wts[inl].sum() < max(0.5 * wts.sum(), ABS_FLOOR):   # hybrid gate: relative + absolute floor
        return img, 0.0
    spread = math.sqrt(float(np.average((angs[inl] - med) ** 2, weights=wts[inl])))
    if spread > 0.7 or abs(med) < rcfg["min_angle"] or abs(med) > rcfg["max_angle"]:
        return img, 0.0
    a = math.radians(abs(med))
    ca, sa, c2 = math.cos(a), math.sin(a), math.cos(2 * a)
    wr, hr = (w * ca - h * sa) / c2, (h * ca - w * sa) / c2
    if wr * hr < rcfg["min_area_keep"] * w * h or wr < 1 or hr < 1:
        return img, 0.0
    rot = img.rotate(med, resample=Image.BICUBIC, expand=True)  # screen-y-down: positive med rotates the tilt back level
    W, H = rot.size
    box = (int((W - wr) / 2), int((H - hr) / 2), int((W + wr) / 2), int((H + hr) / 2))
    return rot.crop(box), med

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
    scale = np.minimum(scale, 2.5)                    # global cap: ~1.3 stops max anywhere
    m = maxc * scale
    soft = 0.9 + 0.08 * np.tanh((m - 0.9) / 0.08)     # smooth shoulder, asymptote 0.98 — filmic, never reaches the ceiling
    scale = np.where(m > 0.9, soft / np.maximum(maxc, 1e-6), scale)
    scale = np.maximum(scale, 1.0)                    # lift-only: never darken a pixel
    return np.clip(arr * scale[..., None], 0, 1), float(p)

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
    import cv2
    img = img.copy()
    img.thumbnail((fcfg["long_edge"], fcfg["long_edge"]), Image.LANCZOS)
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
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))

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
