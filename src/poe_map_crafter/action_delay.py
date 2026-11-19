from __future__ import annotations

import random
import time
from typing import Callable

import pyautogui


class ActionDelay:
    """Случайные задержки между последовательными действиями."""

    def __init__(self, min_ms: int = 150, max_ms: int = 350) -> None:
        self.set_range(min_ms, max_ms)

    def set_range(self, min_ms: int, max_ms: int) -> None:
        if min_ms < 0 or max_ms < 0:
            raise ValueError("Задержки не могут быть отрицательными")
        if min_ms > max_ms:
            min_ms, max_ms = max_ms, min_ms
        self._min_ms = min_ms
        self._max_ms = max_ms

    def wait(self) -> float:
        delay_ms = random.randint(self._min_ms, self._max_ms)
        delay_s = delay_ms / 1000.0
        time.sleep(delay_s)
        return delay_s

    def wait_fixed(self, ms: int) -> None:
        time.sleep(max(0, ms) / 1000.0)


class ClickJitter:
    """Случайное смещение точки клика относительно центра ячейки."""

    def __init__(self, min_px: int = 1, max_px: int = 4) -> None:
        self.set_range(min_px, max_px)

    def set_range(self, min_px: int, max_px: int) -> None:
        if min_px < 0 or max_px < 0:
            raise ValueError("Разброс клика не может быть отрицательным")
        if min_px > max_px:
            min_px, max_px = max_px, min_px
        self._min_px = min_px
        self._max_px = max_px

    def apply(self, screen_x: int, screen_y: int) -> tuple[int, int]:
        if self._max_px == 0:
            return screen_x, screen_y

        for _ in range(8):
            dx = random.randint(-self._max_px, self._max_px)
            dy = random.randint(-self._max_px, self._max_px)
            if self._min_px == 0:
                return screen_x + dx, screen_y + dy
            if max(abs(dx), abs(dy)) >= self._min_px:
                return screen_x + dx, screen_y + dy

        sign_x = random.choice((-1, 1))
        sign_y = random.choice((-1, 1))
        return screen_x + sign_x * self._min_px, screen_y + sign_y * self._min_px


class InputController:
    """Единый контроллер ввода: все клики проходят через задержки и разброс координат."""

    def __init__(
        self,
        action_delay: ActionDelay,
        pyautogui_pause: float = 0.05,
        should_abort: Callable[[], bool] | None = None,
        click_jitter: ClickJitter | None = None,
    ) -> None:
        pyautogui.PAUSE = pyautogui_pause
        pyautogui.FAILSAFE = True
        self._delay = action_delay
        self._jitter = click_jitter or ClickJitter()
        self._should_abort = should_abort or (lambda: False)

    def set_click_jitter(self, min_px: int, max_px: int) -> None:
        self._jitter.set_range(min_px, max_px)

    def wait_fixed(self, ms: int) -> None:
        self._delay.wait_fixed(ms)

    def _check_abort(self) -> None:
        if self._should_abort():
            from .exceptions import SafetyStopError

            raise SafetyStopError("Остановка по запросу безопасности")

    def hover(self, screen_x: int, screen_y: int) -> None:
        self._check_abort()
        x, y = self._jitter.apply(screen_x, screen_y)
        pyautogui.moveTo(x, y)

    def click(
        self,
        screen_x: int,
        screen_y: int,
        *,
        button: str = "left",
        delay_after: bool = True,
    ) -> None:
        self._check_abort()
        x, y = self._jitter.apply(screen_x, screen_y)
        pyautogui.moveTo(x, y)
        if delay_after:
            self._delay.wait()
        self._check_abort()
        pyautogui.click(x, y, button=button)
        if delay_after:
            self._delay.wait()

    def right_click(self, screen_x: int, screen_y: int, *, delay_after: bool = True) -> None:
        self.click(screen_x, screen_y, button="right", delay_after=delay_after)

    def apply_currency_pair(self, orb_xy: tuple[int, int], target_xy: tuple[int, int]) -> None:
        """PoE: ПКМ по орбу → наведение на цель → ЛКМ."""
        self.right_click(orb_xy[0], orb_xy[1])
        self._delay.wait()
        self._check_abort()
        x, y = self._jitter.apply(target_xy[0], target_xy[1])
        pyautogui.moveTo(x, y)
        self._delay.wait()
        self._check_abort()
        pyautogui.click(x, y, button="left")
        self._delay.wait()