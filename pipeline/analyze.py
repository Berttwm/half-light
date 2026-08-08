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
