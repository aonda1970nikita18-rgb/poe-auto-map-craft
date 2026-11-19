from __future__ import annotations

from .action_delay import ActionDelay, InputController
from .config import AppConfig
from .exceptions import CraftingError
from .inventory_catalog import CurrencyLedger
from .inventory_scanner import CurrencyPosition
from .safety_controller import SafetyController


class CurrencyController:
    def __init__(
        self,
        config: AppConfig,
        input_controller: InputController,
        action_delay: ActionDelay,
        safety: SafetyController,
    ) -> None:
        self._config = config
        self._input = input_controller
        self._delay = action_delay
        self._safety = safety
        self._ledger: CurrencyLedger | None = None

    def bind_ledger(self, ledger: CurrencyLedger) -> None:
        self._ledger = ledger

    def apply_scouring(
        self,
        scouring: CurrencyPosition,
        target_screen_xy: tuple[int, int],
    ) -> None:
        self._safety.check_runtime()
        self._input.apply_currency_pair(scouring.screen_center, target_screen_xy)
        self._delay.wait_fixed(self._config.action_wait_after_currency_ms)

    def apply_alchemy(
        self,
        alchemy: CurrencyPosition,
        target_screen_xy: tuple[int, int],
    ) -> None:
        self._safety.check_runtime()
        self._input.apply_currency_pair(alchemy.screen_center, target_screen_xy)
        self._delay.wait_fixed(self._config.action_wait_after_craft_ms)

    def craft_cycle(
        self,
        scouring: CurrencyPosition,
        alchemy: CurrencyPosition,
        target_screen_xy: tuple[int, int],
    ) -> None:
        self.apply_scouring(scouring, target_screen_xy)
        self.apply_alchemy(alchemy, target_screen_xy)
        if self._ledger is not None:
            self._ledger.consume_pair()

    def verify_pair_available(self, currency: dict[str, CurrencyPosition]) -> None:
        if "scouring" not in currency or "alchemy" not in currency:
            raise CraftingError("В инвентаре отсутствует необходимая валюта")