from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from .action_delay import ActionDelay, ClickJitter, InputController
from .calibration import (
    GridCalibration,
    format_region,
    region_from_grid_centers,
    save_layout_debug_image,
)
from .calibration_wizard import capture_cursor_on_hotkey
from .config import AppConfig
from .cursor_release import release_poe_cursor
from .constants import ProgramState
from .crafting_engine import CraftingEngine
from .currency_controller import CurrencyController
from .inventory_probe import InventoryProbe
from .inventory_scanner import InventoryScanner
from .safety_controller import SafetyController
from .screen_detector import ScreenDetector
from .stash_scanner import StashScanner
from .statistics import Statistics
from .preflight import run_preflight
from .window_utils import ScreenCapture, WindowFinder


STATE_LABELS = {
    ProgramState.IDLE: "Ожидание",
    ProgramState.INITIALIZING: "Инициализация",
    ProgramState.RUNNING: "В процессе",
    ProgramState.STOPPING: "Останавливается",
    ProgramState.STOPPED: "Остановлено",
    ProgramState.COMPLETED: "Завершено",
    ProgramState.ERROR: "Ошибка",
}


class CrafterApp:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._stats = Statistics()
        self._ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self._window_finder = WindowFinder(config.window_title_substrings)
        self._capture = ScreenCapture()
        self._action_delay = ActionDelay(
            config.delays_ms["min"],
            config.delays_ms["max"],
        )
        self._safety = SafetyController(
            self._window_finder,
            config.emergency_hotkey,
            on_log=lambda msg: self._enqueue("log", msg),
            on_release_cursor=self._release_game_cursor,
            release_cursor_on_stop=bool(getattr(config, "release_cursor_on_stop", True)),
        )
        self._click_jitter = ClickJitter(
            config.click_jitter_px["min"],
            config.click_jitter_px["max"],
        )
        self._input = InputController(
            self._action_delay,
            pyautogui_pause=config.pyautogui_pause,
            should_abort=self._safety.should_stop,
            click_jitter=self._click_jitter,
        )
        self._stash = StashScanner(config, self._capture)
        self._inventory = InventoryScanner(config, self._capture)
        self._inventory_probe = InventoryProbe(config, self._capture, self._inventory)
        self._screen = ScreenDetector(
            config,
            self._window_finder,
            self._capture,
            self._inventory,
            self._inventory_probe,
        )
        self._currency = CurrencyController(config, self._input, self._action_delay, self._safety)
        self._engine = CraftingEngine(
            config,
            self._screen,
            self._stash,
            self._currency,
            self._safety,
            self._stats,
            self._input,
            on_state_change=self._on_state_change,
            on_log=lambda msg: self._enqueue("log", msg),
            on_stats_update=lambda stats: self._enqueue("stats", stats),
        )

        self._root = tk.Tk()
        self._root.title("PoE Map Crafter")
        self._root.geometry("560x720")
        self._root.minsize(480, 640)
        self._calibration_busy = False
        self._build_ui()
        self._poll_queue()
        self._show_welcome_log()
        self._safety.register_hotkey()

    def _release_game_cursor(self) -> None:
        release_poe_cursor(
            self._window_finder,
            escape_presses=int(getattr(self._config, "release_cursor_escape_presses", 2)),
        )
        self._enqueue("log", "Курсор в игре сброшен (Escape).")

    def _build_ui(self) -> None:
        root = self._root
        pad = {"padx": 10, "pady": 6}

        header = ttk.Label(root, text="PoE Map Crafter", font=("Segoe UI", 16, "bold"))
        header.pack(anchor="w", **pad)

        self._status_var = tk.StringVar(value="Статус: Ожидание")
        ttk.Label(root, textvariable=self._status_var, font=("Segoe UI", 11)).pack(anchor="w", **pad)

        stats_frame = ttk.LabelFrame(root, text="Прогресс")
        stats_frame.pack(fill="x", **pad)

        self._maps_total_var = tk.StringVar(value="Обнаружено карт: 0")
        self._maps_ok_var = tk.StringVar(value="Подходящих карт: 0")
        self._maps_gray_var = tk.StringVar(value="Неподходящих карт: 0")
        self._maps_progress_var = tk.StringVar(value="Обработано: 0/0")
        self._current_map_var = tk.StringVar(value="Текущая карта: —")
        self._scouring_var = tk.StringVar(value="Orb of Scouring: 0")
        self._alchemy_var = tk.StringVar(value="Orb of Alchemy: 0")

        for var in (
            self._maps_total_var,
            self._maps_ok_var,
            self._maps_gray_var,
            self._maps_progress_var,
            self._current_map_var,
            self._scouring_var,
            self._alchemy_var,
        ):
            ttk.Label(stats_frame, textvariable=var).pack(anchor="w", padx=8, pady=2)

        currency_frame = ttk.LabelFrame(root, text="Валюта в инвентаре")
        currency_frame.pack(fill="x", **pad)

        self._currency_mode = tk.StringVar(value=self._config.currency_mode)
        mode_row = ttk.Frame(currency_frame)
        mode_row.pack(fill="x", padx=8, pady=4)
        ttk.Radiobutton(
            mode_row,
            text="Искать орбы (обход инвентаря)",
            variable=self._currency_mode,
            value="probe",
            command=self._on_currency_mode_change,
        ).pack(anchor="w")
        ttk.Radiobutton(
            mode_row,
            text="Фиксированные слоты (как на раскладке)",
            variable=self._currency_mode,
            value="fixed",
            command=self._on_currency_mode_change,
        ).pack(anchor="w")

        from .currency_layout import stacks_summary

        self._fixed_slots_frame = ttk.Frame(currency_frame)
        self._fixed_slots_frame.pack(fill="x", padx=8, pady=(0, 6))
        summary = stacks_summary(self._config.fixed_currency_slots)
        ttk.Label(
            self._fixed_slots_frame,
            text=summary,
            wraplength=520,
        ).pack(anchor="w", pady=2)
        ttk.Label(
            currency_frame,
            text=(
                "Порядок: слева направо, сверху вниз. Scouring cols 0–4, Alchemy cols 5–11. "
                "Список [col, row, стопка] в config/default_config.json → fixed_currency_slots."
            ),
            wraplength=520,
            foreground="#444",
        ).pack(anchor="w", padx=8, pady=(0, 4))

        self._on_currency_mode_change()

        delay_frame = ttk.LabelFrame(root, text="Задержки между действиями (мс)")
        delay_frame.pack(fill="x", **pad)

        self._delay_min = tk.IntVar(value=self._config.delays_ms["min"])
        self._delay_max = tk.IntVar(value=self._config.delays_ms["max"])

        row = ttk.Frame(delay_frame)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="Минимум").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(row, from_=50, to=2000, textvariable=self._delay_min, width=8).grid(
            row=0, column=1, padx=8
        )
        ttk.Label(row, text="Максимум").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(row, from_=50, to=3000, textvariable=self._delay_max, width=8).grid(
            row=0, column=3, padx=8
        )

        jitter_row = ttk.Frame(delay_frame)
        jitter_row.pack(fill="x", padx=8, pady=(0, 4))
        self._jitter_min = tk.IntVar(value=self._config.click_jitter_px["min"])
        self._jitter_max = tk.IntVar(value=self._config.click_jitter_px["max"])
        ttk.Label(jitter_row, text="Разброс клика (px), мин").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(jitter_row, from_=0, to=30, textvariable=self._jitter_min, width=8).grid(
            row=0, column=1, padx=8
        )
        ttk.Label(jitter_row, text="макс").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(jitter_row, from_=0, to=30, textvariable=self._jitter_max, width=8).grid(
            row=0, column=3, padx=8
        )

        btns = ttk.Frame(root)
        btns.pack(fill="x", **pad)
        self._start_btn = ttk.Button(btns, text="Старт", command=self._on_start, width=12)
        self._start_btn.pack(side="left", padx=(0, 8))
        self._stop_btn = ttk.Button(btns, text="Стоп", command=self._on_stop, state="disabled", width=12)
        self._stop_btn.pack(side="left", padx=(0, 8))
        self._check_btn = ttk.Button(btns, text="Проверка", command=self._on_check, width=12)
        self._check_btn.pack(side="left")

        calib = ttk.LabelFrame(root, text="Калибровка сетки (если курсор мимо слотов)")
        calib.pack(fill="x", **pad)
        calib_row = ttk.Frame(calib)
        calib_row.pack(fill="x", padx=8, pady=6)
        self._layout_btn = ttk.Button(
            calib_row, text="Скриншот сетки", command=self._on_save_layout, width=16
        )
        self._layout_btn.pack(side="left", padx=(0, 8))
        self._calib_inv_btn = ttk.Button(
            calib_row,
            text="Инвентарь F8→F9",
            command=lambda: self._start_grid_calibration("inventory"),
            width=18,
        )
        self._calib_inv_btn.pack(side="left", padx=(0, 8))
        self._calib_stash_btn = ttk.Button(
            calib_row,
            text="Сундук F6→F7",
            command=lambda: self._start_grid_calibration("stash"),
            width=16,
        )
        self._calib_stash_btn.pack(side="left")
        ttk.Label(
            calib,
            text=(
                "Наведите на центр ячейки [0,0], нажмите первую клавишу, "
                "затем центр противоположного угла сетки — вторую клавишу."
            ),
            wraplength=520,
            foreground="#444",
        ).pack(anchor="w", padx=8, pady=(0, 6))

        ttk.Label(
            root,
            text=(
                f"Аварийная остановка + сброс курсора: {self._config.emergency_hotkey.upper()} "
                f"(Escape в PoE)"
            ),
        ).pack(anchor="w", **pad)

        log_frame = ttk.LabelFrame(root, text="Лог")
        log_frame.pack(fill="both", expand=True, **pad)
        self._log = scrolledtext.ScrolledText(log_frame, height=16, state="disabled", wrap="word")
        self._log.pack(fill="both", expand=True, padx=6, pady=6)

        hint = (
            "Перед запуском: вкладка T16 в сундуке, открыт инвентарь со Scouring и Alchemy, "
            "в строке поиска сундука введён regex. Окно PoE должно оставаться активным."
        )
        ttk.Label(root, text=hint, wraplength=520, foreground="#444").pack(anchor="w", **pad)

    def _enqueue(self, kind: str, payload: object) -> None:
        self._ui_queue.put((kind, payload))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "stats":
                    self._update_stats(payload)  # type: ignore[arg-type]
                elif kind == "state":
                    self._update_state(payload)  # type: ignore[arg-type]
                elif kind == "calib_busy":
                    self._set_calibration_busy(bool(payload))
        except queue.Empty:
            pass
        self._root.after(120, self._poll_queue)

    def _on_state_change(self, state: ProgramState) -> None:
        self._enqueue("state", state)

    def _update_state(self, state: ProgramState) -> None:
        self._status_var.set(f"Статус: {STATE_LABELS.get(state, state.value)}")
        running = state in (ProgramState.INITIALIZING, ProgramState.RUNNING, ProgramState.STOPPING)
        self._start_btn.config(state="disabled" if running else "normal")
        self._stop_btn.config(state="normal" if running else "disabled")

    def _update_stats(self, stats: Statistics) -> None:
        gray = stats.maps_gray
        processed = stats.maps_processed
        self._maps_total_var.set(f"Обнаружено карт: {stats.maps_total}")
        self._maps_ok_var.set(f"Подходящих карт: {stats.maps_highlighted}")
        self._maps_gray_var.set(f"Неподходящих карт: {gray}")
        target = stats.maps_gray_initial or gray
        self._maps_progress_var.set(f"Обработано: {processed}/{target}")
        current = stats.current_map_index
        self._current_map_var.set(
            f"Текущая карта: {current}" if current else "Текущая карта: —"
        )
        self._scouring_var.set(f"Orb of Scouring: {stats.scouring_used}")
        self._alchemy_var.set(f"Orb of Alchemy: {stats.alchemy_used}")

    def _append_log(self, message: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", message + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _on_currency_mode_change(self) -> None:
        pass

    def _apply_currency_settings(self) -> None:
        mode = self._currency_mode.get()
        self._config.currency_mode = mode
        self._config.sync_currency_mode()

    def _apply_delay_settings(self) -> None:
        self._apply_currency_settings()

        min_ms = int(self._delay_min.get())
        max_ms = int(self._delay_max.get())
        self._action_delay.set_range(min_ms, max_ms)
        self._config.delays_ms = {"min": min_ms, "max": max_ms}

        jitter_min = int(self._jitter_min.get())
        jitter_max = int(self._jitter_max.get())
        self._click_jitter.set_range(jitter_min, jitter_max)
        self._config.click_jitter_px = {"min": jitter_min, "max": jitter_max}

    def _show_welcome_log(self) -> None:
        self._append_log("PoE Map Crafter готов.")
        self._append_log(
            "Статус «Ожидание» — норма до начала крафта. Сначала подготовьте игру, "
            "затем «Проверка», затем «Старт» (окно PoE должно быть активно)."
        )
        self._append_log(
            "1) Сундук T16  2) Инвентарь со Scouring и Alchemy  3) regex в поиске сундука"
        )
        self._append_log(
            "Режим валюты: «Искать орбы» — обход инвентаря; «Фиксированные слоты» — без сканирования."
        )
        self._append_log(
            "Если слоты смещены — «Скриншот сетки», затем «Инвентарь F8→F9» (сундук: F6→F7)."
        )

    def _set_calibration_busy(self, busy: bool) -> None:
        self._calibration_busy = busy
        state = "disabled" if busy else "normal"
        for btn in (
            self._layout_btn,
            self._calib_inv_btn,
            self._calib_stash_btn,
            self._start_btn,
            self._check_btn,
        ):
            btn.config(state=state)

    def _on_save_layout(self) -> None:
        if self._engine.state in (ProgramState.RUNNING, ProgramState.INITIALIZING):
            self._append_log("Скриншот недоступен во время крафта.")
            return
        window = self._window_finder.find()
        if window is None:
            messagebox.showerror("PoE", "Окно Path of Exile не найдено.")
            return
        try:
            path = save_layout_debug_image(window, self._capture, self._config)
        except OSError as exc:
            self._append_log(f"Не удалось сохранить скриншот: {exc}")
            return
        self._append_log(f"Скриншот сетки сохранён: {path}")
        self._append_log("Жёлтая сетка — сундук, зелёная — инвентарь. Подгоните калибровкой.")

    def _start_grid_calibration(self, target: str) -> None:
        if self._calibration_busy:
            return
        if self._engine.state in (ProgramState.RUNNING, ProgramState.INITIALIZING):
            self._append_log("Калибровка недоступна во время крафта.")
            return
        thread = threading.Thread(
            target=self._run_grid_calibration,
            args=(target,),
            name=f"Calib-{target}",
            daemon=True,
        )
        thread.start()

    def _run_grid_calibration(self, target: str) -> None:
        self._enqueue("calib_busy", True)
        try:
            window = self._window_finder.find()
            if window is None:
                self._enqueue("log", "Калибровка: окно Path of Exile не найдено.")
                return

            if target == "inventory":
                region_cfg = self._config.inventory
                key_a, key_b = "f8", "f9"
                title = "инвентаря"
                last = (region_cfg.columns - 1, region_cfg.rows - 1)
            else:
                region_cfg = self._config.stash
                key_a, key_b = "f6", "f7"
                title = "сундука"
                last = (region_cfg.columns - 1, region_cfg.rows - 1)

            self._enqueue(
                "log",
                f"Калибровка {title}: наведите на центр ячейки [0,0] и нажмите {key_a.upper()}.",
            )
            p0 = capture_cursor_on_hotkey(key_a)
            if p0 is None:
                self._enqueue("log", "Калибровка отменена (таймаут первой точки).")
                return

            self._enqueue(
                "log",
                f"Точка 1: {p0[0]},{p0[1]}. "
                f"Наведите на ячейку [{last[0]},{last[1]}] и нажмите {key_b.upper()}.",
            )
            p1 = capture_cursor_on_hotkey(key_b)
            if p1 is None:
                self._enqueue("log", "Калибровка отменена (таймаут второй точки).")
                return

            c0 = window.screen_to_client(p0[0], p0[1])
            c1 = window.screen_to_client(p1[0], p1[1])
            new_region = region_from_grid_centers(
                window.client_rect,
                GridCalibration(c0, c1, region_cfg.columns, region_cfg.rows),
            )

            if target == "inventory":
                self._config.inventory = new_region
            else:
                self._config.stash = new_region

            self._config.save()
            path = save_layout_debug_image(window, self._capture, self._config)
            self._enqueue("log", f"Калибровка {title} сохранена: {format_region(new_region)}")
            self._enqueue("log", f"Проверочный скриншот: {path}")
        except ValueError as exc:
            self._enqueue("log", f"Калибровка: {exc}")
        except Exception as exc:  # noqa: BLE001
            self._enqueue("log", f"Калибровка: ошибка {exc}")
        finally:
            self._enqueue("calib_busy", False)

    def _on_check(self) -> None:
        if self._engine.state in (ProgramState.RUNNING, ProgramState.INITIALIZING):
            self._append_log("Проверка недоступна во время крафта.")
            return
        self._append_log("———")
        for line in run_preflight(
            self._config,
            self._window_finder,
            self._capture,
            self._stash,
            self._inventory,
        ):
            self._append_log(line)
        self._append_log("———")

    def _on_start(self) -> None:
        if self._engine.state in (ProgramState.RUNNING, ProgramState.INITIALIZING):
            return
        self._apply_delay_settings()
        self._append_log("Запуск крафта… переключитесь на окно Path of Exile.")
        self._update_state(ProgramState.INITIALIZING)
        self._engine.start()

    def _on_stop(self) -> None:
        self._engine.stop()
        self._append_log("Запрошена остановка…")

    def run(self) -> None:
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.mainloop()

    def _on_close(self) -> None:
        if self._engine.state in (ProgramState.RUNNING, ProgramState.INITIALIZING):
            if not messagebox.askyesno("Выход", "Крафт выполняется. Остановить и выйти?"):
                return
            self._engine.stop()
            self._safety.release_cursor()
        self._safety.unregister_hotkey()
        self._root.destroy()


def run_gui(config: AppConfig | None = None) -> None:
    cfg = config or AppConfig.load()
    CrafterApp(cfg).run()