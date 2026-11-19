from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .exceptions import CurrencyError
from .inventory_scanner import CurrencyPosition
from .tooltip_reader import classify_currency_kind


@dataclass
class InventorySlotItem:
    row: int
    col: int
    screen_center: tuple[int, int]
    item_name: str | None
    stack_size: int
    currency_kind: str | None = None
    source: str = "tooltip"


@dataclass
class InventoryCatalog:
    slots: list[InventorySlotItem] = field(default_factory=list)

    @property
    def occupied_slots(self) -> list[InventorySlotItem]:
        return [s for s in self.slots if s.item_name and s.stack_size > 0]

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        for slot in self.occupied_slots:
            label = slot.item_name or "?"
            kind = f" [{slot.currency_kind}]" if slot.currency_kind else ""
            lines.append(f"  [{slot.col},{slot.row}] {label} ×{slot.stack_size}{kind}")
        return lines

    def normalize_currency_kinds(self) -> None:
        for slot in self.slots:
            if slot.currency_kind:
                continue
            name = slot.item_name or ""
            if len(name) > 44:
                continue
            slot.currency_kind = classify_currency_kind(name)

    def resolve_currency(self, require_both: bool = True) -> dict[str, CurrencyPosition]:
        self.normalize_currency_kinds()
        positions: dict[str, CurrencyPosition] = {}
        for kind in ("scouring", "alchemy"):
            candidates = [s for s in self.slots if s.currency_kind == kind and s.stack_size > 0]
            if not candidates:
                if require_both:
                    label = "Orb of Scouring" if kind == "scouring" else "Orb of Alchemy"
                    raise CurrencyError(f"Не найдена валюта в инвентаре: {label}")
                continue
            best = max(candidates, key=lambda s: s.stack_size)
            positions[kind] = CurrencyPosition(
                kind=kind,
                row=best.row,
                col=best.col,
                screen_center=best.screen_center,
                stack_size=best.stack_size,
            )
        if require_both and len(positions) < 2:
            raise CurrencyError("Нужны Orb of Scouring и Orb of Alchemy в инвентаре.")
        return positions


class CurrencyLedger:
    def __init__(
        self,
        stacks_by_kind: dict[str, list[CurrencyPosition]],
        on_stack_advance: Callable[[str, CurrencyPosition], None] | None = None,
    ) -> None:
        self._on_stack_advance = on_stack_advance
        self._entries: dict[str, list[tuple[CurrencyPosition, int]]] = {}
        for kind, positions in stacks_by_kind.items():
            self._entries[kind] = [(p, max(1, p.stack_size)) for p in positions]
        self._index: dict[str, int] = {kind: 0 for kind in self._entries}

    def remaining(self, kind: str) -> int:
        total = 0
        for i, (_pos, rem) in enumerate(self._entries.get(kind, [])):
            if i < self._index.get(kind, 0):
                continue
            total += rem
        return total

    def position(self, kind: str) -> CurrencyPosition:
        idx = self._index.get(kind, 0)
        entries = self._entries.get(kind, [])
        if idx >= len(entries):
            name = "Orb of Scouring" if kind == "scouring" else "Orb of Alchemy"
            raise CurrencyError(f"Закончилась валюта: {name}")
        pos, rem = entries[idx]
        return CurrencyPosition(
            kind=pos.kind,
            row=pos.row,
            col=pos.col,
            screen_center=pos.screen_center,
            stack_size=rem,
        )

    def consume_pair(self) -> None:
        for kind in ("scouring", "alchemy"):
            idx = self._index.get(kind, 0)
            entries = self._entries.get(kind, [])
            if idx >= len(entries):
                name = "Orb of Scouring" if kind == "scouring" else "Orb of Alchemy"
                raise CurrencyError(f"Закончилась валюта: {name}")
            pos, rem = entries[idx]
            rem -= 1
            if rem <= 0:
                idx += 1
                self._index[kind] = idx
                if idx < len(entries):
                    next_pos, _ = entries[idx]
                    if self._on_stack_advance is not None:
                        self._on_stack_advance(kind, next_pos)
            else:
                entries[idx] = (pos, rem)
