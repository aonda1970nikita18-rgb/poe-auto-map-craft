from __future__ import annotations

from typing import Callable

import pyautogui

from .action_delay import InputController
from .config import AppConfig
from .image_analysis import orb_detection_scores
from .inventory_catalog import InventoryCatalog, InventorySlotItem
from .inventory_scanner import InventoryScanner, _extract_patch
from .safety_controller import SafetyController
from .stack_reader import parse_stack_from_text, read_stack_from_cell_patch
from .tooltip_reader import (
    classify_orb_from_tooltip,
    ocr_image,
    ocr_runtime_available,
    ocr_setup_hint,
    parse_tooltip,
    tooltip_panel_visible,
)
from .window_utils import GameWindow, ScreenCapture, ScreenRect, cell_inset


class InventoryProbe:
    def __init__(
        self,
        config: AppConfig,
        capture: ScreenCapture,
        inventory: InventoryScanner,
    ) -> None:
        self._config = config
        self._capture = capture
        self._inventory = inventory

    def scan(
        self,
        window: GameWindow,
        input_controller: InputController,
        safety: SafetyController,
        on_log: Callable[[str], None] | None = None,
    ) -> InventoryCatalog:
        log = on_log or (lambda _m: None)
        probe = self._config.inventory_probe
        cells = self._inventory.inventory_cells(window)
        total = len(cells)
        catalog = InventoryCatalog()
        cell_patches: dict[tuple[int, int], object] = {}

        log(
            f"Сканирование инвентаря ({total} слотов): наведение курсора и чтение подсказок…"
        )
        log(ocr_setup_hint())
        if not ocr_runtime_available():
            log("Без Tesseract размер стопки может быть неточным (орбы ищем по иконке).")
        log("Не шевелите мышь, окно Path of Exile должно быть активно.")

        hover_wait_ms = int(probe.get("hover_wait_ms", 380))
        settle_ms = int(probe.get("hover_settle_ms", 120))
        progress_step = max(1, self._config.inventory.columns)
        det = self._config.detection

        for index, cell in enumerate(cells, start=1):
            safety.check_runtime()
            input_controller.hover(cell.screen_center[0], cell.screen_center[1])
            input_controller.wait_fixed(hover_wait_ms)

            ocr_text = ""
            name: str | None = None
            stack = 1
            source = "vision"

            for tooltip in self._capture_tooltips(probe):
                if not tooltip_panel_visible(tooltip):
                    continue
                ocr_text = ocr_image(tooltip)
                if not ocr_text.strip():
                    continue
                parsed_name, parsed_stack = parse_tooltip(ocr_text)
                if parsed_name and len(parsed_name) <= 44:
                    name = parsed_name
                if parsed_stack > 0:
                    stack = parsed_stack
                if classify_orb_from_tooltip(ocr_text):
                    source = "tooltip"
                    break

            input_controller.wait_fixed(settle_ms)
            frame = self._capture.capture_client(window)
            patch = _extract_patch(frame, cell_inset(cell.client_rect))
            key = (cell.col, cell.row)
            cell_patches[key] = patch

            if not self._looks_occupied(patch):
                continue

            if not name:
                name = "Предмет"

            catalog.slots.append(
                InventorySlotItem(
                    row=cell.row,
                    col=cell.col,
                    screen_center=cell.screen_center,
                    item_name=name,
                    stack_size=max(1, stack),
                    currency_kind=None,
                    source=source,
                )
            )

            if index == 1 or index == total or index % progress_step == 0:
                log(f"  Инвентарь: {index}/{total} слотов…")

        self._assign_orbs_by_best_score(catalog, cell_patches, det, log)
        self._refresh_orb_stack_sizes(
            window, input_controller, safety, catalog, cells, log
        )

        occupied = len(catalog.occupied_slots)
        log(f"Сканирование завершено: занято слотов {occupied}.")
        for line in catalog.summary_lines()[:25]:
            log(line)
        if occupied > 25:
            log(f"  … и ещё {occupied - 25} предметов.")
        return catalog

    def _assign_orbs_by_best_score(
        self,
        catalog: InventoryCatalog,
        patches: dict[tuple[int, int], object],
        detection: dict[str, float],
        log: Callable[[str], None],
    ) -> None:
        best: dict[str, tuple[float, InventorySlotItem]] = {}

        for slot in catalog.slots:
            patch = patches.get((slot.col, slot.row))
            if patch is None:
                continue
            scour, alch = orb_detection_scores(patch, detection)
            if scour > best.get("scouring", (0.0, slot))[0]:
                best["scouring"] = (scour, slot)
            if alch > best.get("alchemy", (0.0, slot))[0]:
                best["alchemy"] = (alch, slot)

        min_gap = float(detection.get("orb_score_min", 0.09))

        for kind, label in (("scouring", "Orb of Scouring"), ("alchemy", "Orb of Alchemy")):
            entry = best.get(kind)
            if not entry or entry[0] < min_gap:
                log(f"  {label}: не найден (лучший score {entry[0]:.3f})" if entry else f"  {label}: не найден")
                continue
            slot = entry[1]
            slot.currency_kind = kind
            slot.item_name = label
            slot.source = f"{slot.source}+orb_score"
            log(f"  {label}: ячейка [{slot.col},{slot.row}], score={entry[0]:.3f}, ×{slot.stack_size}")

    def _refresh_orb_stack_sizes(
        self,
        window: GameWindow,
        input_controller: InputController,
        safety: SafetyController,
        catalog: InventoryCatalog,
        cells: list,
        log: Callable[[str], None],
    ) -> None:
        probe = self._config.inventory_probe
        hover_ms = int(probe.get("hover_wait_ms", 380))
        fallback = self._config.currency_stack_fallback
        use_fallback = bool(fallback.get("use_when_unread", True))
        cells_by_pos = {(c.col, c.row): c for c in cells}

        log("Подсчёт стопок орбов (tooltip + цифры на иконке)…")

        for slot in catalog.slots:
            if slot.currency_kind not in ("scouring", "alchemy"):
                continue

            safety.check_runtime()
            input_controller.hover(slot.screen_center[0], slot.screen_center[1])
            input_controller.wait_fixed(hover_ms)

            tooltip_stack = 0
            for tooltip in self._capture_tooltips(probe):
                if not tooltip_panel_visible(tooltip):
                    continue
                text = ocr_image(tooltip)
                if classify_orb_from_tooltip(text) != slot.currency_kind:
                    continue
                tooltip_stack = parse_stack_from_text(text)
                break

            cell = cells_by_pos.get((slot.col, slot.row))
            cell_stack: int | None = None
            if cell is not None:
                frame = self._capture.capture_client(window)
                patch = _extract_patch(frame, cell_inset(cell.client_rect))
                cell_stack = read_stack_from_cell_patch(patch)

            candidates = [v for v in (tooltip_stack, cell_stack or 0) if v and v > 0]
            if candidates:
                slot.stack_size = max(candidates)
            elif use_fallback:
                slot.stack_size = int(fallback.get(slot.currency_kind, 1))
            else:
                slot.stack_size = max(1, tooltip_stack)

            if slot.stack_size <= 1 and use_fallback:
                fb = int(fallback.get(slot.currency_kind, 1))
                if fb > 1:
                    slot.stack_size = fb
                    log(
                        f"  {slot.item_name}: стопка не прочитана OCR, "
                        f"взято из config fallback = {fb}"
                    )
                    continue

            log(
                f"  {slot.item_name}: стопка {slot.stack_size} "
                f"(tooltip={tooltip_stack or '—'}, ячейка={cell_stack or '—'})"
            )

    def _capture_tooltips(self, probe: dict):
        cx, cy = pyautogui.position()
        width = int(probe.get("tooltip_width", 450))
        height = int(probe.get("tooltip_height", 240))
        offsets = (
            (
                int(probe.get("tooltip_offset_x", 20)),
                int(probe.get("tooltip_offset_y", -140)),
            ),
            (-width - 20, int(probe.get("tooltip_offset_y", -140))),
        )
        for ox, oy in offsets:
            left = max(0, cx + ox)
            top = max(0, cy + oy)
            yield self._capture.capture_screen_rect(ScreenRect(left, top, width, height))

    @staticmethod
    def _looks_occupied(patch) -> bool:
        return float(patch.mean()) >= 22