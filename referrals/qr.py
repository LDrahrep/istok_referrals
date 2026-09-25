"""Чтение ID сотрудника (EMP-<uuid>) с фото QR-кода на бейдже."""
from __future__ import annotations

import io

import numpy as np
import zxingcpp
from PIL import Image, ImageOps, UnidentifiedImageError

from referrals.validation import parse_emp_id


def decode_emp_id(data: bytes) -> str | None:
    try:
        image = Image.open(io.BytesIO(data))
        gray = ImageOps.exif_transpose(image).convert("L")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
    for attempt in (gray, ImageOps.autocontrast(gray, cutoff=2)):
        for code in zxingcpp.read_barcodes(np.asarray(attempt), formats=zxingcpp.BarcodeFormat.QRCode):
            emplid = parse_emp_id(code.text)
            if emplid:
                return emplid
    return None
