from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import AppConfig
from .exceptions import CurrencyError
from .image_analysis import detect_alchemy, detect_scouring
from .window_utils import (
    GameWindow,
    ScreenCapture,
    ScreenRect,
    cell_inset,
    iter_grid_cells,
    ratios_to_rect,
)


@dataclass(frozen=True)
class CurrencyPosition:
    kind: str
    row: int
    col: int
    screen_center: tuple[int, int]
    stack_size: int = 1


class InventoryScanner:
    def __init__(self, config: AppConfig, capture: ScreenCapture) -> None:
        self._config = config
        self._capture = capture

    def find_currency(self, window: GameWindow) -> dict[str, CurrencyPosition]:
        scouring_slot = self._config.currency_slots.get("scouring")
        alchemy_slot = self._config.currency_slots.get("alchemy")

        if scouring_slot and alchemy_slot:
            return self._positions_from_slots(window, scouring_slot, alchemy_slot)

        detected = self._detect_currency(window)
        if "scouring" not in detected or "alchemy" not in detected:
            missing = []
            if "scouring" not in detected:
                missing.append("Orb of Scouring")
            if "alchemy" not in detected:
                missing.append("Orb of Alchemy")
            raise CurrencyError(
                "Не найдена валюта в инвентаре: " + ", ".join(missing)
                + ". Укажите слоты в config/default_config.json при необходимости."
            )
        return detected

    def positions_for_fixed_stacks(
        self,
        window: GameWindow,
        kind: str,
        stacks: list[tuple[int, int, int]],
    ) -> list[CurrencyPosition]:
        cells = self.inventory_cells(window)
        by_coord = {(c.col, c.row): c for c in cells}
        out: list[CurrencyPosition] = []
        for col, row, stack_size in stacks:
            cell = by_coord.get((col, row))
            if cell is None:
                raise CurrencyError(
                    f"Слот валюты [{col},{row}] ({kind}) вне сетки инвентаря"
                )
            out.append(
                CurrencyPosition(
                    kind, cell.row, cell.col, cell.screen_center, stack_size
                )
            )
        return out

    def _positions_from_slots(
        self,
        window: GameWindow,
        scouring: tuple[int, int],
        alchemy: tuple[int, int],
    ) -> dict[str, CurrencyPosition]:
        cells = self.inventory_cells(window)
        by_coord = {(c.col, c.row): c for c in cells}
        sc = by_coord.get(scouring)
        al = by_coord.get(alchemy)
        if sc is None or al is None:
            raise CurrencyError("Указанные слоты валюты выходят за пределы инвентаря")
        return {
            "scouring": CurrencyPosition("scouring", sc.row, sc.col, sc.screen_center),
            "alchemy": CurrencyPosition("alchemy", al.row, al.col, al.screen_center),
        }

    def _detect_currency(self, window: GameWindow) -> dict[str, CurrencyPosition]:
        frame = self._capture.capture_client(window)
        cells = self.inventory_cells(window)
        found: dict[str, CurrencyPosition] = {}
        for cell in cells:
            patch = _extract_patch(frame, cell_inset(cell.client_rect))
            if _cell_empty(patch):
                continue
            if "scouring" not in found and detect_scouring(patch, self._config.detection):
                found["scouring"] = CurrencyPosition(
                    "scouring", cell.row, cell.col, cell.screen_center
                )
            if "alchemy" not in found and detect_alchemy(patch, self._config.detection):
                found["alchemy"] = CurrencyPosition(
                    "alchemy", cell.row, cell.col, cell.screen_center
                )
        return found

    def inventory_cells(self, window: GameWindow) -> list[_InvCell]:
        region = ratios_to_rect(window.client_rect, self._config.inventory)
        rects = iter_grid_cells(
            region,
            self._config.inventory.columns,
            self._config.inventory.rows,
        )
        cells: list[_InvCell] = []
        for idx, rect in enumerate(rects):
            row = idx // self._config.inventory.columns
            col = idx % self._config.inventory.columns
            sx, sy = window.client_to_screen(*rect.center)
            cells.append(_InvCell(row, col, rect, (sx, sy)))
        return cells


@dataclass
class _InvCell:
    row: int
    col: int
    client_rect: ScreenRect
    screen_center: tuple[int, int]


def _extract_patch(frame: np.ndarray, rect: ScreenRect) -> np.ndarray:
    x0 = max(0, rect.left)
    y0 = max(0, rect.top)
    x1 = min(frame.shape[1], rect.right)
    y1 = min(frame.shape[0], rect.bottom)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    return frame[y0:y1, x0:x1]


def _cell_empty(patch: np.ndarray) -> bool:
    gray = patch.mean()
    return float(gray) < 22