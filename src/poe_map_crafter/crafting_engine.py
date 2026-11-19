from __future__ import annotations

import threading
from typing import Callable

from .action_delay import InputController
from .config import AppConfig
from .constants import CellState, ProgramState
from .currency_controller import CurrencyController
from .exceptions import PoECrafterError, RecognitionError, SafetyStopError
from .safety_controller import SafetyController
from .screen_detector import RuntimeContext, ScreenDetector
from .statistics import Statistics
from .image_analysis import map_cell_is_ready, map_cell_needs_craft
from .stash_scanner import MapCell, StashScanner


class CraftingEngine:
    def __init__(
        self,
        config: AppConfig,
        screen_detector: ScreenDetector,
        stash_scanner: StashScanner,
        currency: CurrencyController,
        safety: SafetyController,
        statistics: Statistics,
        input_controller: InputController,
        on_state_change: Callable[[ProgramState], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        on_stats_update: Callable[[Statistics], None] | None = None,
    ) -> None:
        self._config = config
        self._screen = screen_detector
        self._stash = stash_scanner
        self._currency = currency
        self._safety = safety
        self._stats = statistics
        self._on_state_change = on_state_change or (lambda _s: None)
        self._on_log = on_log or (lambda _m: None)
        self._on_stats_update = on_stats_update or (lambda _s: None)
        self._input = input_controller
        self._thread: threading.Thread | None = None
        self._state = ProgramState.IDLE
        self._context: RuntimeContext | None = None

    @property
    def state(self) -> ProgramState:
        return self._state

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._safety.clear_stop()
        self._stats.reset()
        self._thread = threading.Thread(target=self._run, name="CraftingEngine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._safety.request_stop("Стоп: остановка и сброс курсора…", release_cursor=True)
        self._set_state(ProgramState.STOPPING)

    def _set_state(self, state: ProgramState) -> None:
        self._state = state
        self._on_state_change(state)

    def _run(self) -> None:
        try:
            self._set_state(ProgramState.INITIALIZING)
            self._on_log("Инициализация: поиск окна и элементов интерфейса...")
            self._context = self._screen.initialize(
                self._input,
                self._safety,
                on_log=self._on_log,
            )
            self._safety.bind_window(self._context.window)
            self._safety.register_hotkey()
            self._currency.bind_ledger(self._context.ledger)
            self._currency.verify_pair_available(self._context.currency)
            self._stats.start_timer()
            self._set_state(ProgramState.RUNNING)
            self._craft_all_maps()
            self._stats.stop_timer()
            if self._safety.should_stop:
                self._set_state(ProgramState.STOPPED)
                self._on_log("Работа остановлена.")
            else:
                self._set_state(ProgramState.COMPLETED)
                leftover = (
                    self._stash.count_maps_needing_craft(window) if self._context else 0
                )
                initial = self._stats.maps_gray_initial
                done = self._stats.maps_processed
                if leftover or (initial and done < initial):
                    self._on_log(
                        f"Обработано карт: {done} из {initial} на старте; "
                        f"сейчас не под фильтром: ~{leftover}. "
                        "Нажмите Старт снова или подстройте detection в config."
                    )
                else:
                    self._on_log("Неподходящих карт не осталось (по распознаванию).")
            for line in self._stats.summary_lines():
                self._on_log(line)
        except (PoECrafterError, SafetyStopError) as exc:
            self._stats.stop_timer()
            self._set_state(ProgramState.ERROR)
            self._on_log(f"Ошибка: {exc}")
        except Exception as exc:  # noqa: BLE001
            self._stats.stop_timer()
            self._set_state(ProgramState.ERROR)
            self._on_log(f"Неожиданная ошибка: {exc}")
        finally:
            if self._safety.should_stop:
                self._safety.release_cursor()
            self._safety.unregister_hotkey()
            self._on_stats_update(self._stats)

    def _craft_all_maps(self) -> None:
        assert self._context is not None
        window = self._context.window

        gray_maps = self._stash.maps_to_craft(window)
        if not gray_maps:
            self._on_log("Неподходящих карт не найдено.")
            return

        self._stats.maps_gray_initial = len(gray_maps)
        cells = self._stash.scan(window)
        self._refresh_stats(cells)

        ledger = self._context.ledger
        self._on_log(
            f"Запас валюты после сканирования: Scouring {ledger.remaining('scouring')}, "
            f"Alchemy {ledger.remaining('alchemy')}"
        )
        if ledger.remaining("scouring") == 0 or ledger.remaining("alchemy") == 0:
            from .exceptions import CurrencyError

            raise CurrencyError("Недостаточно валюты для начала крафта.")

        validation_done = False
        maps_processed = 0

        while True:
            self._safety.check_runtime()
            gray_maps = self._stash.maps_to_craft(window)
            if not gray_maps:
                break

            map_cell = gray_maps[0]
            maps_processed += 1
            self._stats.current_map_index = maps_processed
            self._on_log(
                f"Крафт карты {maps_processed} (ячейка {map_cell.row},{map_cell.col}), "
                f"осталось серых: {len(gray_maps)}"
            )
            self._craft_single_map(window, map_cell)
            self._stats.maps_processed += 1

            if self._config.run_validation_on_first_map and not validation_done:
                validation_done = True
                self._on_log("Проверка на первой карте завершена — продолжаем пакетную обработку.")

            cells = self._stash.scan(window)
            self._refresh_stats(cells)

    def _craft_single_map(
        self,
        window,
        map_cell: MapCell,
    ) -> None:
        assert self._context is not None
        ledger = self._context.ledger
        iterations = 0

        while iterations < self._config.max_craft_iterations_per_map:
            self._safety.check_runtime()

            if self._stash.cell_matches_filter(window, map_cell):
                self._stats.maps_succeeded += 1
                self._on_log(f"Карта {map_cell.row},{map_cell.col} подходит по фильтру.")
                return

            if not self._stash.cell_has_item(window, map_cell):
                raise RecognitionError(
                    f"Ячейка {map_cell.row},{map_cell.col} пуста — крафт невозможен"
                )

            patch = self._stash.read_cell_patch(window, map_cell)
            det = self._config.detection
            if map_cell_is_ready(patch, det):
                self._stats.maps_succeeded += 1
                self._on_log(
                    f"Карта {map_cell.row},{map_cell.col} уже подходит — крафт пропущен."
                )
                return
            if not map_cell_needs_craft(patch, det):
                patch = self._stash.read_cell_patch_settled(window, map_cell)
                if map_cell_is_ready(patch, det):
                    self._stats.maps_succeeded += 1
                    self._on_log(
                        f"Карта {map_cell.row},{map_cell.col} уже подходит (повторная проверка)."
                    )
                    return
                if not map_cell_needs_craft(patch, det):
                    self._on_log(
                        f"Карта {map_cell.row},{map_cell.col}: статус неясен, пробуем крафт."
                    )

            scouring = ledger.position("scouring")
            alchemy = ledger.position("alchemy")
            self._currency.craft_cycle(scouring, alchemy, map_cell.screen_center)
            self._stats.scouring_used += 1
            self._stats.alchemy_used += 1
            self._stats.craft_iterations += 1
            iterations += 1
            self._on_stats_update(self._stats)

            if self._stash.cell_matches_filter(window, map_cell):
                self._stats.maps_succeeded += 1
                self._on_log(f"Карта {map_cell.row},{map_cell.col} успешно перекрафчена.")
                return

            if not self._stash.cell_has_item(window, map_cell):
                raise RecognitionError("Карта исчезла после крафта — остановка.")

            patch = self._stash.read_cell_patch_settled(window, map_cell)
            if map_cell_needs_craft(patch, det):
                self._on_log(
                    f"Карта {map_cell.row},{map_cell.col} ещё не под фильтр — следующий цикл орбов."
                )
                continue

        raise RecognitionError(
            f"Превышен лимит итераций ({self._config.max_craft_iterations_per_map}) "
            f"для ячейки {map_cell.row},{map_cell.col}"
        )

    def _refresh_stats(self, cells: list[MapCell]) -> None:
        total, highlighted, gray = self._stash.summarize(cells)
        self._stats.update_scan(total, highlighted, gray)
        self._on_stats_update(self._stats)