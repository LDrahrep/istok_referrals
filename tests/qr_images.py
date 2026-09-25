"""Синтетические «фото бейджа» для тестов QR."""
import io

import numpy as np
import qrcode
from PIL import Image


def qr_image(text: str, size: int = 300) -> Image.Image:
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=10)
    code.add_data(text)
    code.make(fit=True)
    img = code.make_image(fill_color="black", back_color="white").convert("L")
    return img.resize((size, size), Image.NEAREST)


def in_scene(img: Image.Image, width: int = 1280, height: int = 960) -> Image.Image:
    rng = np.random.default_rng(1)
    background = Image.fromarray(np.clip(rng.normal(150, 35, (height, width)), 0, 255).astype("uint8"))
    background.paste(img, ((width - img.width) // 2, (height - img.height) // 2))
    return background


def to_bytes(img: Image.Image, fmt: str = "JPEG") -> bytes:
    buffer = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buffer, fmt, quality=80)
    else:
        img.save(buffer, fmt)
    return buffer.getvalue()


def qr_photo_jpeg(text: str) -> bytes:
    return to_bytes(in_scene(qr_image(text)))


def blank_photo_jpeg() -> bytes:
    return to_bytes(in_scene(Image.new("L", (300, 300), 235)))
