from __future__ import annotations

import re

import cv2
import numpy as np

from .tooltip_reader import ocr_runtime_available, parse_tooltip

_STACK_DIGITS = re.compile(r"\b(\d{1,5})\b")


def parse_stack_from_text(text: str) -> int:
    _, stack = parse_tooltip(text)
    if stack > 1:
        return stack
    for pattern in (
        re.compile(r"stack size:\s*(\d+)", re.I),
        re.compile(r"stack:\s*(\d+)", re.I),
        re.compile(r"размер стопки:\s*(\d+)", re.I),
        re.compile(r"(\d+)\s*/\s*(\d+)"),
    ):
        match = pattern.search(text)
        if match:
            if match.lastindex and match.lastindex >= 2:
                return int(match.group(1))
            return int(match.group(1))
    numbers = [int(m.group(1)) for m in _STACK_DIGITS.finditer(text)]
    numbers = [n for n in numbers if 1 <= n <= 9999]
    return max(numbers) if numbers else 1


def read_stack_from_cell_patch(patch: np.ndarray) -> int | None:
    """Цифра стопки в правом нижнем углу ячейки (PoE)."""
    if patch.size == 0 or patch.shape[0] < 8:
        return None

    h, w = patch.shape[:2]
    x0 = int(w * 0.45)
    y0 = int(h * 0.55)
    crop = patch[y0:h, x0:w]
    if crop.size == 0:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    bright = gray >= 165
    ratio = float(np.count_nonzero(bright)) / bright.size
    if ratio < 0.008:
        return None

    scaled = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(scaled, 150, 255, cv2.THRESH_BINARY)

    if not ocr_runtime_available():
        return _estimate_stack_from_blobs(thresh)

    import pytesseract

    try:
        text = pytesseract.image_to_string(
            thresh, config="--psm 7 -c tessedit_char_whitelist=0123456789"
        )
    except pytesseract.TesseractError:
        text = pytesseract.image_to_string(thresh, config="--psm 7")
    text = text.strip()
    if not text:
        return _estimate_stack_from_blobs(thresh)
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    value = int(digits)
    return value if value >= 1 else None


def _estimate_stack_from_blobs(thresh: np.ndarray) -> int | None:
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    areas = [cv2.contourArea(c) for c in contours]
    if max(areas) < 12:
        return None
    return None