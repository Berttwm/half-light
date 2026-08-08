import io
import math
import numpy as np
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
