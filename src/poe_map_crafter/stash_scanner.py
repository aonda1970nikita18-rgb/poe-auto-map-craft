from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .config import AppConfig
from .constants import CellState
from .exceptions import RecognitionError
from .image_analysis import (
    cell_appears_occupied,
    classify_stash_cell,
    map_cell_is_ready,
    map_cell_needs_craft,
)
from .window_utils import (
    GameWindow,
    ScreenCapture,
    ScreenRect,
    cell_inset,
    iter_grid_cells,
    ratios_to_rect,
)


@dataclass(frozen=True)
class MapCell:
    index: int
    row: int
    col: int
    client_rect: ScreenRect
    screen_center: tuple[int, int]
    state: CellState


class StashScanner:
    def __init__(self, config: AppConfig, capture: ScreenCapture) -> None:
        self._config = config
        self._capture = capture

    def scan(self, window: GameWindow) -> list[MapCell]:
        client = window.client_rect
        stash_region = ratios_to_rect(client, self._config.stash)
        frame = self._capture.capture_client(window)
        cells = iter_grid_cells(
            stash_region,
            self._config.stash.columns,
            self._config.stash.rows,
        )
        results: list[MapCell] = []
        for idx, cell_rect in enumerate(cells):
            inset = cell_inset(cell_rect)
            patch = _extract_patch(frame, inset)
            state = classify_stash_cell(patch, self._config.detection)
            sx, sy = window.client_to_screen(*cell_rect.center)
            row = idx // self._config.stash.columns
            col = idx % self._config.stash.columns
            results.append(MapCell(idx, row, col, cell_rect, (sx, sy), state))
        return results

    def read_cell_patch(self, window: GameWindow, cell: MapCell) -> np.ndarray:
        frame = self._capture.capture_client(window)
        inset = cell_inset(cell.client_rect)
        return _extract_patch(frame, inset)

    def read_cell_state(self, window: GameWindow, cell: MapCell) -> CellState:
        patch = self.read_cell_patch(window, cell)
        return classify_stash_cell(patch, self._config.detection)

    def read_cell_patch_settled(self, window: GameWindow, cell: MapCell) -> np.ndarray:
        delays = self._config.stash_recheck_delays_ms
        last_patch = self.read_cell_patch(window, cell)
        for ms in delays:
            if ms > 0:
                time.sleep(ms / 1000.0)
            last_patch = self.read_cell_patch(window, cell)
            if map_cell_is_ready(last_patch, self._config.detection):
                return last_patch
        return last_patch

    def cell_matches_filter(self, window: GameWindow, cell: MapCell) -> bool:
        patch = self.read_cell_patch_settled(window, cell)
        return map_cell_is_ready(patch, self._config.detection)

    def cell_has_item(self, window: GameWindow, cell: MapCell) -> bool:
        patch = self.read_cell_patch_settled(window, cell)
        return cell_appears_occupied(patch, self._config.detection)

    def gray_map_cells(self, window: GameWindow) -> list[MapCell]:
        cells = self.scan(window)
        frame = self._capture.capture_client(window)
        det = self._config.detection
        gray: list[MapCell] = []
        for cell in cells:
            patch = _extract_patch(frame, cell_inset(cell.client_rect))
            if map_cell_needs_craft(patch, det):
                gray.append(cell)
        return gray

    def maps_to_craft(self, window: GameWindow) -> list[MapCell]:
        gray = self.gray_map_cells(window)
        if gray:
            return gray
        cells = self.scan(window)
        return [c for c in cells if c.state is CellState.GRAY]

    def count_maps_needing_craft(self, window: GameWindow) -> int:
        return len(self.maps_to_craft(window))

    def classify_cell(self, window: GameWindow, cell: MapCell) -> CellState:
        patch = self.read_cell_patch_settled(window, cell)
        det = self._config.detection
        if not cell_appears_occupied(patch, det):
            return CellState.EMPTY
        if map_cell_needs_craft(patch, det):
            return CellState.GRAY
        return CellState.HIGHLIGHTED

    def summarize(self, cells: list[MapCell]) -> tuple[int, int, int]:
        occupied = [c for c in cells if c.state is not CellState.EMPTY]
        highlighted = sum(1 for c in occupied if c.state is CellState.HIGHLIGHTED)
        gray = sum(1 for c in occupied if c.state is CellState.GRAY)
        return len(occupied), highlighted, gray

    def gray_maps(self, cells: list[MapCell]) -> list[MapCell]:
        return [c for c in cells if c.state is CellState.GRAY]

    def highlighted_maps(self, cells: list[MapCell]) -> list[MapCell]:
        return [c for c in cells if c.state is CellState.HIGHLIGHTED]


def _extract_patch(frame: np.ndarray, rect: ScreenRect) -> np.ndarray:
    x0 = max(0, rect.left)
    y0 = max(0, rect.top)
    x1 = min(frame.shape[1], rect.right)
    y1 = min(frame.shape[0], rect.bottom)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    return frame[y0:y1, x0:x1]