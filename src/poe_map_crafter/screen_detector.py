from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .action_delay import InputController
from .config import AppConfig
from .exceptions import InitializationError
from .image_analysis import search_bar_has_filter
from .inventory_catalog import CurrencyLedger, InventoryCatalog
from .inventory_probe import InventoryProbe
from .inventory_scanner import CurrencyPosition, InventoryScanner
from .safety_controller import SafetyController
from .window_utils import GameWindow, ScreenCapture, WindowFinder, ratios_to_rect


@dataclass
class RuntimeContext:
    window: GameWindow
    currency: dict[str, CurrencyPosition]
    catalog: InventoryCatalog
    ledger: CurrencyLedger


class ScreenDetector:
    def __init__(
        self,
        config: AppConfig,
        window_finder: WindowFinder,
        capture: ScreenCapture,
        inventory_scanner: InventoryScanner,
        inventory_probe: InventoryProbe | None = None,
    ) -> None:
        self._config = config
        self._window_finder = window_finder
        self._capture = capture
        self._inventory = inventory_scanner
        self._probe = inventory_probe

    def initialize(
        self,
        input_controller: InputController,
        safety: SafetyController,
        on_log: Callable[[str], None] | None = None,
    ) -> RuntimeContext:
        log = on_log or (lambda _m: None)

        window = self._window_finder.find()
        if window is None:
            raise InitializationError(
                "Окно Path of Exile не найдено. Запустите игру и откройте сундук с картами."
            )

        self._window_finder.focus(window.hwnd)

        search_region = ratios_to_rect(window.client_rect, self._config.search_bar)
        search_patch = self._capture.capture_region(window, search_region)
        if not search_bar_has_filter(search_patch):
            raise InitializationError(
                "В строке поиска сундука не обнаружен фильтр. Введите regex перед запуском."
            )

        catalog = InventoryCatalog()

        if self._config.currency_mode == "fixed":
            from .currency_layout import stacks_summary

            log(
                "Режим валюты: список фиксированных стопок с автопереходом. "
                + stacks_summary(self._config.fixed_currency_slots)
            )
            currency = None
        else:
            probe_enabled = bool(self._config.inventory_probe.get("enabled", True))
            if probe_enabled and self._probe is not None:
                safety.bind_window(window)
                catalog = self._probe.scan(window, input_controller, safety, on_log=log)

            scouring_slot = self._config.currency_slots.get("scouring")
            alchemy_slot = self._config.currency_slots.get("alchemy")
            slots_fixed = scouring_slot is not None and alchemy_slot is not None

            if slots_fixed:
                currency = self._merge_fixed_slots(window, catalog)
            elif catalog.occupied_slots:
                currency = catalog.resolve_currency(require_both=True)
            else:
                currency = self._inventory.find_currency(window)

        assert currency is not None or self._config.currency_mode == "fixed"
        stacks_by_kind = self._build_currency_stacks(window, currency)
        ledger = CurrencyLedger(
            stacks_by_kind,
            on_stack_advance=lambda kind, pos: log(
                f"Следующая стопка {kind}: [{pos.col},{pos.row}]"
            ),
        )
        active = {k: ledger.position(k) for k in ("scouring", "alchemy")}
        sc, al = active["scouring"], active["alchemy"]
        log(
            f"Валюта для крафта: Scouring [{sc.col},{sc.row}] ×{sc.stack_size} "
            f"(всего {ledger.remaining('scouring')}), "
            f"Alchemy [{al.col},{al.row}] ×{al.stack_size} "
            f"(всего {ledger.remaining('alchemy')})"
        )
        return RuntimeContext(
            window=window,
            currency=active,
            catalog=catalog,
            ledger=ledger,
        )

    def _build_currency_stacks(
        self,
        window: GameWindow,
        currency: dict[str, CurrencyPosition] | None,
    ) -> dict[str, list[CurrencyPosition]]:
        if self._config.currency_mode == "fixed":
            self._config.sync_currency_mode()
            stacks_cfg = self._config.fixed_currency_slots
            return {
                "scouring": self._inventory.positions_for_fixed_stacks(
                    window, "scouring", stacks_cfg.get("scouring", [])
                ),
                "alchemy": self._inventory.positions_for_fixed_stacks(
                    window, "alchemy", stacks_cfg.get("alchemy", [])
                ),
            }
        assert currency is not None
        return {
            "scouring": [currency["scouring"]],
            "alchemy": [currency["alchemy"]],
        }

    def _merge_fixed_slots(
        self, window: GameWindow, catalog: InventoryCatalog
    ) -> dict[str, CurrencyPosition]:
        currency = self._inventory.find_currency(window)
        merged: dict[str, CurrencyPosition] = {}
        for kind, pos in currency.items():
            match = next(
                (s for s in catalog.slots if s.col == pos.col and s.row == pos.row),
                None,
            )
            stack = match.stack_size if match else pos.stack_size
            merged[kind] = CurrencyPosition(
                kind=kind,
                row=pos.row,
                col=pos.col,
                screen_center=pos.screen_center,
                stack_size=stack,
            )
        return merged