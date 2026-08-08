import io
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
