from __future__ import annotations

import time

import pyautogui

from .window_utils import GameWindow, WindowFinder


def release_poe_cursor(
    window_finder: WindowFinder,
    window: GameWindow | None = None,
    *,
    escape_presses: int = 2,
    pause_ms: int = 80,
) -> None:
    """Снять орб/предмет с курсора в PoE (обычно Escape)."""
    target = window
    if target is None:
        target = window_finder.find()
    if target is not None:
        window_finder.focus(target.hwnd)
        time.sleep(0.05)

    for _ in range(max(1, escape_presses)):
        pyautogui.press("escape")
        time.sleep(max(0, pause_ms) / 1000.0)