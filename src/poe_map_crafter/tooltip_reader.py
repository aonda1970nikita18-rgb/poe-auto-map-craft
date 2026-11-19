from __future__ import annotations

import re
import shutil
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

STACK_PATTERNS = (
    re.compile(r"stack size:\s*(\d+)", re.IGNORECASE),
    re.compile(r"stack:\s*(\d+)", re.IGNORECASE),
    re.compile(r"размер стопки:\s*(\d+)", re.IGNORECASE),
    re.compile(r"в стопке:\s*(\d+)", re.IGNORECASE),
    re.compile(r"\b(\d{1,5})\s*/\s*\d+\b"),
)

CURRENCY_KINDS: dict[str, tuple[str, ...]] = {
    "scouring": (
        "orb of scouring",
        "сфера очищения",
        "scouring",
        "scour",
        "очищ",
    ),
    "alchemy": (
        "orb of alchemy",
        "сфера алхимии",
        "alchemy",
        "alch",
        "алхим",
    ),
}

_FUZZY_KIND_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "scouring": (
        re.compile(r"scou?r", re.IGNORECASE),
        re.compile(r"очищ", re.IGNORECASE),
        re.compile(r"\b0rb\b.*scou", re.IGNORECASE),
    ),
    "alchemy": (
        re.compile(r"alch", re.IGNORECASE),
        re.compile(r"алхим", re.IGNORECASE),
    ),
}

_TESSERACT_HINT = (
    "Установите Tesseract OCR для Windows: "
    "https://github.com/UB-Mannheim/tesseract/wiki "
    "(при установке отметьте English; при русском клиенте — Russian)."
)

_WINDOWS_TESSERACT_PATHS = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)


def tooltip_panel_visible(patch: np.ndarray, min_std: float = 18.0) -> bool:
    if patch.size == 0:
        return False
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    return float(np.std(gray)) >= min_std


@lru_cache(maxsize=1)
def ocr_runtime_available() -> bool:
    try:
        import pytesseract
    except ImportError:
        return False

    if shutil.which("tesseract"):
        return True

    for candidate in _WINDOWS_TESSERACT_PATHS:
        if candidate.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return True
    return False


def ocr_setup_hint() -> str:
    if ocr_runtime_available():
        return "OCR (Tesseract): доступен."
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return "OCR: установите пакет pytesseract (pip install pytesseract). " + _TESSERACT_HINT
    return "OCR: Tesseract не найден в PATH. " + _TESSERACT_HINT


def _prepare_for_ocr(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    scaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return cv2.threshold(scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def ocr_image(bgr: np.ndarray) -> str:
    if bgr.size == 0 or not ocr_runtime_available():
        return ""

    import pytesseract

    prepared = _prepare_for_ocr(bgr)
    langs = "eng+rus"
    try:
        text = pytesseract.image_to_string(prepared, lang=langs, config="--psm 6")
    except pytesseract.TesseractError:
        text = pytesseract.image_to_string(prepared, lang="eng", config="--psm 6")
    return text.strip()


def parse_tooltip(text: str) -> tuple[str | None, int]:
    cleaned = text.strip()
    if not cleaned:
        return None, 0

    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    item_name = _pick_item_name(lines)
    stack_size = 1
    for pattern in STACK_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            stack_size = int(match.group(1))
            break
    return item_name, stack_size


def _pick_item_name(lines: list[str]) -> str | None:
    if not lines:
        return None
    for line in lines:
        lowered = line.lower()
        if any(
            needle in lowered
            for needles in CURRENCY_KINDS.values()
            for needle in needles
        ):
            return line
    return lines[0]


def classify_currency_kind(item_name: str | None) -> str | None:
    if not item_name:
        return None
    return classify_currency_in_text(item_name)


def classify_currency_in_text(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for kind, needles in CURRENCY_KINDS.items():
        if any(needle in lowered for needle in needles):
            return kind
    for kind, patterns in _FUZZY_KIND_PATTERNS.items():
        if any(pattern.search(text) for pattern in patterns):
            return kind
    return None


def classify_orb_from_tooltip(text: str) -> str | None:
    """Только короткие строки заголовка подсказки, без описания («upgrades…»)."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or len(line) > 44:
            continue
        if "upgrades" in line.lower() or "normal item" in line.lower():
            continue
        if "улучшает" in line.lower() or "обычн" in line.lower():
            continue
        kind = classify_currency_in_text(line)
        if kind:
            return kind
    return None