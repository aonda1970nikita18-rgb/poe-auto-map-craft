from __future__ import annotations

import cv2
import numpy as np

from .constants import CellState


def cell_appears_occupied(patch: np.ndarray, detection: dict[str, float]) -> bool:
    if patch.size == 0:
        return False
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    mean_brightness = float(np.mean(gray))
    texture_std = float(np.std(gray))
    empty_max = detection.get("empty_brightness_max", 22)
    std_min = detection.get("cell_texture_std_min", 8.0)
    if mean_brightness >= empty_max:
        return True
    if texture_std >= std_min:
        return True
    if mean_brightness >= empty_max * 0.45 and texture_std >= std_min * 0.65:
        return True
    return False


def stash_filter_dimmed(patch: np.ndarray, detection: dict[str, float]) -> bool:
    """Только явно приглушённый фильтром лут (и sat, и val низкие)."""
    if not cell_appears_occupied(patch, detection):
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    sat_mean = float(np.mean(hsv[:, :, 1]))
    val_mean = float(np.mean(hsv[:, :, 2]))

    ready_val = detection.get("stash_ready_value_min", 86)
    ready_sat = detection.get("stash_ready_saturation_min", 44)
    if val_mean >= ready_val or sat_mean >= ready_sat:
        return False

    dim_sat = detection.get("gray_saturation_max", 38)
    dim_val = detection.get("stash_gray_value_max", 78)
    return sat_mean <= dim_sat and val_mean <= dim_val


def stash_cell_highlighted(patch: np.ndarray, detection: dict[str, float]) -> bool:
    """Карта подсвечена фильтром сундука (прошла regex) — крафт не нужен."""
    if not cell_appears_occupied(patch, detection):
        return False
    if stash_filter_dimmed(patch, detection):
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    sat_mean = float(np.mean(hsv[:, :, 1]))
    val_mean = float(np.mean(hsv[:, :, 2]))
    ready_val = detection.get("stash_ready_value_min", 86)
    ready_sat = detection.get("stash_ready_saturation_min", 44)
    highlight_sat_min = detection.get("highlight_saturation_min", 50)
    if sat_mean >= highlight_sat_min:
        return True
    if val_mean >= ready_val and sat_mean >= ready_sat * 0.85:
        return True
    if val_mean >= 98 and sat_mean >= 35:
        return True
    return False


def map_cell_needs_craft(patch: np.ndarray, detection: dict[str, float]) -> bool:
    if not cell_appears_occupied(patch, detection):
        return False
    return not stash_cell_highlighted(patch, detection)


def map_cell_is_ready(patch: np.ndarray, detection: dict[str, float]) -> bool:
    return stash_cell_highlighted(patch, detection)


def map_matches_stash_filter(state: CellState, patch: np.ndarray, detection: dict[str, float]) -> bool:
    return map_cell_is_ready(patch, detection)


def classify_stash_cell(patch: np.ndarray, detection: dict[str, float]) -> CellState:
    if patch.size == 0 or patch.shape[0] < 2 or patch.shape[1] < 2:
        return CellState.UNKNOWN

    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    mean_brightness = float(np.mean(gray))
    texture_std = float(np.std(gray))
    empty_max = detection.get("empty_brightness_max", 22)

    if mean_brightness < empty_max and texture_std < detection.get("cell_texture_std_min", 11.0):
        return CellState.EMPTY
    if mean_brightness < empty_max * 0.7:
        return CellState.EMPTY

    if not cell_appears_occupied(patch, detection):
        return CellState.EMPTY

    if stash_cell_highlighted(patch, detection):
        return CellState.HIGHLIGHTED
    if stash_filter_dimmed(patch, detection):
        return CellState.GRAY
    return CellState.GRAY


def orb_detection_scores(patch: np.ndarray, detection: dict[str, float]) -> tuple[float, float]:
    """Оценка 0..1 — насколько ячейка похожа на Scouring / Alchemy."""
    if patch.size == 0:
        return 0.0, 0.0

    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]

    scour_sat_max = detection.get("scouring_saturation_max", 65)
    scour_val_min = detection.get("scouring_value_min", 120)
    scour_mask = (val >= scour_val_min) & (sat <= scour_sat_max)
    scour_score = float(np.count_nonzero(scour_mask)) / scour_mask.size

    hue = hsv[:, :, 0]
    alch_mask = (
        (hue >= detection.get("alchemy_hue_min", 12))
        & (hue <= detection.get("alchemy_hue_max", 35))
        & (sat >= detection.get("alchemy_saturation_min", 95))
        & (val >= 80)
    )
    alch_score = float(np.count_nonzero(alch_mask)) / alch_mask.size

    if float(np.mean(sat)) <= scour_sat_max and float(np.mean(val)) >= scour_val_min:
        scour_score = min(1.0, scour_score + 0.05)

    return scour_score, alch_score


def guess_orb_kind(
    patch: np.ndarray,
    detection: dict[str, float],
    *,
    min_score: float | None = None,
) -> str | None:
    threshold = min_score if min_score is not None else detection.get("orb_min_score", 0.09)
    scour, alch = orb_detection_scores(patch, detection)
    if scour < threshold and alch < threshold:
        return None
    if scour >= alch and scour >= threshold:
        return "scouring"
    if alch > scour and alch >= threshold:
        return "alchemy"
    return None


def detect_scouring(patch: np.ndarray, detection: dict[str, float]) -> bool:
    return guess_orb_kind(patch, detection) == "scouring"


def detect_alchemy(patch: np.ndarray, detection: dict[str, float]) -> bool:
    return guess_orb_kind(patch, detection) == "alchemy"


def search_bar_has_filter(patch: np.ndarray) -> bool:
    if patch.size == 0:
        return False
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    std = float(np.std(gray))
    return std > 12.0