from __future__ import annotations

import threading
from typing import Callable

import keyboard

from .exceptions import SafetyStopError
from .window_utils import GameWindow, WindowFinder


class SafetyController:
    def __init__(
        self,
        window_finder: WindowFinder,
        emergency_hotkey: str,
        on_log: Callable[[str], None] | None = None,
        on_release_cursor: Callable[[], None] | None = None,
        release_cursor_on_stop: bool = True,
    ) -> None:
        self._window_finder = window_finder
        self._emergency_hotkey = emergency_hotkey
        self._stop_event = threading.Event()
        self._game_window: GameWindow | None = None
        self._hook_registered = False
        self._on_log = on_log or (lambda _msg: None)
        self._on_release_cursor = on_release_cursor
        self._release_cursor_on_stop = release_cursor_on_stop

    @property
    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def bind_window(self, window: GameWindow) -> None:
        self._game_window = window

    def clear_stop(self) -> None:
        self._stop_event.clear()

    def request_stop(
        self,
        reason: str = "Остановка пользователем",
        *,
        release_cursor: bool | None = None,
    ) -> None:
        self._stop_event.set()
        self._on_log(reason)
        should_release = (
            self._release_cursor_on_stop if release_cursor is None else release_cursor
        )
        if should_release:
            self.release_cursor()

    def release_cursor(self) -> None:
        if self._on_release_cursor is not None:
            try:
                self._on_release_cursor()
            except Exception as exc:  # noqa: BLE001
                self._on_log(f"Не удалось отпустить курсор: {exc}")

    def register_hotkey(self) -> None:
        if self._hook_registered:
            return

        def _on_hotkey() -> None:
            self.request_stop(
                f"Аварийная остановка ({self._emergency_hotkey.upper()}), сброс курсора…",
                release_cursor=True,
            )

        keyboard.add_hotkey(self._emergency_hotkey, _on_hotkey, suppress=False)
        self._hook_registered = True

    def unregister_hotkey(self) -> None:
        if not self._hook_registered:
            return
        try:
            keyboard.remove_hotkey(self._emergency_hotkey)
        except KeyError:
            pass
        self._hook_registered = False

    def check_runtime(self) -> None:
        if self.should_stop:
            raise SafetyStopError("Остановка по запросу")
        if self._game_window is None:
            raise SafetyStopError("Окно игры не привязано")
        if not self._window_finder.is_foreground(self._game_window.hwnd):
            raise SafetyStopError("Потерян фокус окна Path of Exile")