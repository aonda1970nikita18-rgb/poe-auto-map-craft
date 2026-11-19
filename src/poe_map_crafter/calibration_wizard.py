from __future__ import annotations

import pyautogui
from threading import Event

import keyboard


def capture_cursor_on_hotkey(hotkey: str, timeout_sec: float = 180.0) -> tuple[int, int] | None:
    done = Event()
    point: list[tuple[int, int]] = []

    def _handler() -> None:
        point.append(pyautogui.position())
        done.set()

    keyboard.add_hotkey(hotkey, _handler, suppress=False)
    try:
        if not done.wait(timeout=timeout_sec):
            return None
        return point[0]
    finally:
        try:
            keyboard.remove_hotkey(hotkey)
        except KeyError:
            pass