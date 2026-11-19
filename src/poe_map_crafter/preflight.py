from __future__ import annotations

from .config import AppConfig
from .constants import CellState
from .exceptions import CurrencyError
from .image_analysis import search_bar_has_filter
from .inventory_scanner import InventoryScanner
from .stash_scanner import StashScanner
from .window_utils import ScreenCapture, WindowFinder, ratios_to_rect


def run_preflight(
    config: AppConfig,
    window_finder: WindowFinder,
    capture: ScreenCapture,
    stash_scanner: StashScanner,
    inventory_scanner: InventoryScanner,
) -> list[str]:
    lines: list[str] = []
    lines.append("Проверка готовности к крафту…")

    window = window_finder.find()
    if window is None:
        candidates = window_finder.list_matching_titles()
        lines.append("✗ Окно Path of Exile не найдено.")
        if candidates:
            lines.append("  Похожие окна:")
            for title in candidates[:8]:
                lines.append(f"    • {title}")
        else:
            lines.append(
                "  Совет: добавьте фрагмент заголовка окна в config/default_config.json "
                '→ "window_title_substrings".'
            )
        lines.append("  Нажмите «Проверка» снова, когда сундук и инвентарь открыты в игре.")
        return lines

    fg = "да" if window_finder.is_foreground(window.hwnd) else "нет (переключитесь на PoE перед Старт)"
    lines.append(
        f"✓ Окно: «{window.title}» "
        f"({window.client_rect.width}×{window.client_rect.height}), фокус: {fg}"
    )

    search_region = ratios_to_rect(window.client_rect, config.search_bar)
    search_patch = capture.capture_region(window, search_region)
    if search_bar_has_filter(search_patch):
        lines.append("✓ В строке поиска сундука есть текст (regex).")
    else:
        lines.append(
            "✗ Строка поиска сундука пуста или область настроена неверно. "
            "Введите regex в поиск сундука или подстройте search_bar в config."
        )

    if getattr(config, "currency_mode", "probe") == "fixed":
        from .currency_layout import stacks_summary

        lines.append("• Валюта: фиксированные стопки с автопереходом (без обхода).")
        lines.append(f"  {stacks_summary(config.fixed_currency_slots)}")
        sc = config.fixed_currency_slots.get("scouring") or []
        al = config.fixed_currency_slots.get("alchemy") or []
        if sc:
            c, r, n = sc[0]
            lines.append(f"  Старт: Scouring [{c},{r}] ×{n}")
        if al:
            c, r, n = al[0]
            lines.append(f"  Старт: Alchemy [{c},{r}] ×{n}")
    else:
        lines.append(
            "• Валюта: при «Старт» обход инвентаря курсором + чтение подсказок (OCR)."
        )
        if config.inventory_probe.get("enabled", True):
            lines.append("  Не двигайте мышь во время сканирования (~до 30 с).")
    try:
        currency = inventory_scanner.find_currency(window)
        sc = currency["scouring"]
        al = currency["alchemy"]
        lines.append(
            f"  Быстрая проверка (цвет): Scouring [{sc.col},{sc.row}], Alchemy [{al.col},{al.row}]"
        )
    except CurrencyError:
        lines.append(
            "  Быстрая проверка орбов не сработала — это нормально, «Старт» использует OCR."
        )

    cells = stash_scanner.scan(window)
    total, highlighted, gray = stash_scanner.summarize(cells)
    unknown = sum(1 for c in cells if c.state is CellState.UNKNOWN)
    empty = sum(1 for c in cells if c.state is CellState.EMPTY)

    lines.append(
        f"✓ Сундук: карт {total}, подходящих {highlighted}, серых {gray} "
        f"(пустых ячеек {empty}, неопределённых {unknown})"
    )
    if unknown > total // 2 and total > 0:
        lines.append(
            "  Много неопределённых ячеек — проверьте область stash в config/default_config.json."
        )
    if total == 0:
        lines.append("  Карт не видно: откройте вкладку с картами T16 или откалибруйте область сундука.")

    if gray == 0 and total > 0:
        lines.append("  Серых карт нет — крафтить нечего (все уже под фильтр или неверное распознавание).")
    elif gray > 0:
        lines.append(f"  Готово к крафту: после «Старт» обработаем до {gray} серых карт.")

    lines.append("Если всё ✓ — переключитесь на окно PoE и нажмите «Старт».")
    return lines