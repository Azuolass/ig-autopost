"""Convert Drive images (PNG/JPG, any size) to Instagram-ready JPEGs.

The Instagram API accepts JPEG only. Our mockups are 3:4 (1086x1448), which
the app supports; if the API rejects the ratio, the publisher retries with
`pad_to` = 4:5, which adds thin side bars in the image's own edge colour
instead of cropping the artwork.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps, ImageStat


def _edge_colour(img: Image.Image) -> tuple[int, int, int]:
    w, h = img.size
    strip = max(1, w // 50)
    left = img.crop((0, 0, strip, h))
    right = img.crop((w - strip, 0, w, h))
    stats = [ImageStat.Stat(left).mean, ImageStat.Stat(right).mean]
    return tuple(int((a + b) / 2) for a, b in zip(*stats))  # type: ignore[return-value]


def parse_ratio(ratio: str) -> float:
    a, b = ratio.split(":")
    return float(a) / float(b)


def to_instagram_jpeg(
    data: bytes, max_width: int = 1440, quality: int = 92, pad_to: str | None = None
) -> tuple[bytes, tuple[int, int]]:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    icc = img.info.get("icc_profile")
    if icc:  # convert to sRGB so colours stay right once the profile is dropped
        try:
            from PIL import ImageCms

            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            img = ImageCms.profileToProfile(img, src, dst, outputMode=img.mode)
        except Exception:
            pass
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")

    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)

    if pad_to:
        target = parse_ratio(pad_to)  # width / height
        w, h = img.size
        if w / h < target:  # too tall: add side bars
            new_w = round(h * target)
            canvas = Image.new("RGB", (new_w, h), _edge_colour(img))
            canvas.paste(img, ((new_w - w) // 2, 0))
            img = canvas
        elif w / h > 1.91:  # too wide for Instagram: add top/bottom bars
            new_h = round(w / 1.91)
            canvas = Image.new("RGB", (w, new_h), _edge_colour(img))
            canvas.paste(img, (0, (new_h - h) // 2))
            img = canvas

    # Rebuild from raw pixels: no EXIF, XMP, IPTC, ICC, C2PA or any other
    # metadata from the source file survives into the upload.
    clean = Image.frombytes("RGB", img.size, img.tobytes())
    img = clean
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    q = quality
    while out.tell() > 8 * 1024 * 1024 and q > 60:  # Instagram limit: 8 MB
        q -= 8
        out = io.BytesIO()
        img.save(out, "JPEG", quality=q, optimize=True)
    return out.getvalue(), img.size
