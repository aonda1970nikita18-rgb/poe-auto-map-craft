"""Раскладка валюты как на скрине: Scouring cols 0–4, Alchemy cols 5–11."""


def screenshot_currency_layout() -> dict[str, list[tuple[int, int, int]]]:
    """Возвращает (col, row, stack_size) для каждой ячейки, слева направо, сверху вниз."""
    scouring: list[tuple[int, int, int]] = []
    for row in range(5):
        for col in range(5):
            scouring.append((col, row, 30))
    alchemy: list[tuple[int, int, int]] = []
    for row in range(5):
        for col in range(5, 12):
            alchemy.append((col, row, 20))
    return {"scouring": scouring, "alchemy": alchemy}


def stacks_summary(stacks: dict[str, list[tuple[int, int, int]]]) -> str:
    sc = stacks.get("scouring", [])
    al = stacks.get("alchemy", [])
    sc_total = sum(s[2] for s in sc)
    al_total = sum(s[2] for s in al)
    return (
        f"{len(sc)} стопок Scouring (всего {sc_total}), "
        f"{len(al)} стопок Alchemy (всего {al_total})"
    )