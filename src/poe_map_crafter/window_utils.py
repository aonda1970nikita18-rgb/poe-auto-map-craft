from __future__ import annotations

from dataclasses import dataclass
import mss
import mss.tools
import numpy as np
import win32con
import win32gui

from .config import RegionRatios


@dataclass(frozen=True)
class ScreenRect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center(self) -> tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2


@dataclass
class GameWindow:
    hwnd: int
    title: str
    client_rect: ScreenRect

    def client_to_screen(self, x: int, y: int) -> tuple[int, int]:
        return win32gui.ClientToScreen(self.hwnd, (x, y))

    def screen_to_client(self, screen_x: int, screen_y: int) -> tuple[int, int]:
        return win32gui.ScreenToClient(self.hwnd, (int(screen_x), int(screen_y)))


class WindowFinder:
    def __init__(self, title_substrings: list[str]) -> None:
        self._title_substrings = [s.lower() for s in title_substrings]

    def list_matching_titles(self) -> list[str]:
        matches: list[tuple[int, str]] = []
        self._collect_matches(matches)
        return [title for _, title in matches]

    def find(self) -> GameWindow | None:
        matches: list[tuple[int, str]] = []
        self._collect_matches(matches)
        if not matches:
            return None
        hwnd, title = matches[0]
        return self._window_from_match(hwnd, title)

    def _collect_matches(self, matches: list[tuple[int, str]]) -> None:
        def enum_handler(hwnd: int, _: int) -> None:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            lowered = title.lower()
            if any(part in lowered for part in self._title_substrings):
                matches.append((hwnd, title))

        win32gui.EnumWindows(enum_handler, 0)

    def _window_from_match(self, hwnd: int, title: str) -> GameWindow:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        return GameWindow(
            hwnd=hwnd,
            title=title,
            client_rect=ScreenRect(left, top, right - left, bottom - top),
        )

    def is_foreground(self, hwnd: int) -> bool:
        return win32gui.GetForegroundWindow() == hwnd

    def focus(self, hwnd: int) -> None:
        if not win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except win32gui.error:
            pass


class ScreenCapture:
    def __init__(self) -> None:
        self._sct = mss.mss()

    def capture_client(self, window: GameWindow) -> np.ndarray:
        origin_x, origin_y = window.client_to_screen(0, 0)
        monitor = {
            "left": origin_x,
            "top": origin_y,
            "width": window.client_rect.width,
            "height": window.client_rect.height,
        }
        shot = self._sct.grab(monitor)
        bgra = np.array(shot)
        return bgra[:, :, :3].copy()

    def capture_region(self, window: GameWindow, rect: ScreenRect) -> np.ndarray:
        frame = self.capture_client(window)
        x0 = max(0, rect.left)
        y0 = max(0, rect.top)
        x1 = min(frame.shape[1], rect.right)
        y1 = min(frame.shape[0], rect.bottom)
        if x1 <= x0 or y1 <= y0:
            return np.zeros((1, 1, 3), dtype=np.uint8)
        return frame[y0:y1, x0:x1].copy()

    def capture_screen_rect(self, rect: ScreenRect) -> np.ndarray:
        if rect.width <= 0 or rect.height <= 0:
            return np.zeros((1, 1, 3), dtype=np.uint8)
        monitor = {
            "left": rect.left,
            "top": rect.top,
            "width": rect.width,
            "height": rect.height,
        }
        shot = self._sct.grab(monitor)
        bgra = np.array(shot)
        return bgra[:, :, :3].copy()


def ratios_to_rect(client: ScreenRect, ratios: RegionRatios) -> ScreenRect:
    left = int(client.width * ratios.left)
    top = int(client.height * ratios.top)
    width = int(client.width * ratios.width)
    height = int(client.height * ratios.height)
    return ScreenRect(left, top, width, height)


def iter_grid_cells(region: ScreenRect, columns: int, rows: int) -> list[ScreenRect]:
    if columns <= 0 or rows <= 0:
        return []
    cell_w = region.width // columns
    cell_h = region.height // rows
    cells: list[ScreenRect] = []
    for row in range(rows):
        for col in range(columns):
            left = region.left + col * cell_w
            top = region.top + row * cell_h
            cells.append(ScreenRect(left, top, cell_w, cell_h))
    return cells


def cell_inset(rect: ScreenRect, inset_ratio: float = 0.15) -> ScreenRect:
    dx = int(rect.width * inset_ratio)
    dy = int(rect.height * inset_ratio)
    return ScreenRect(
        rect.left + dx,
        rect.top + dy,
        max(1, rect.width - 2 * dx),
        max(1, rect.height - 2 * dy),
    )