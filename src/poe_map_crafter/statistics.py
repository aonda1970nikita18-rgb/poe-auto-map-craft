from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Statistics:
    maps_total: int = 0
    maps_highlighted: int = 0
    maps_gray: int = 0
    maps_gray_initial: int = 0
    maps_processed: int = 0
    maps_succeeded: int = 0
    current_map_index: int = 0
    scouring_used: int = 0
    alchemy_used: int = 0
    craft_iterations: int = 0
    started_at: float | None = None
    finished_at: float | None = None

    def reset(self) -> None:
        self.maps_total = 0
        self.maps_highlighted = 0
        self.maps_gray = 0
        self.maps_gray_initial = 0
        self.maps_processed = 0
        self.maps_succeeded = 0
        self.current_map_index = 0
        self.scouring_used = 0
        self.alchemy_used = 0
        self.craft_iterations = 0
        self.started_at = None
        self.finished_at = None

    def start_timer(self) -> None:
        self.started_at = time.monotonic()
        self.finished_at = None

    def stop_timer(self) -> None:
        self.finished_at = time.monotonic()

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0.0, end - self.started_at)

    def update_scan(self, total: int, highlighted: int, gray: int) -> None:
        self.maps_total = total
        self.maps_highlighted = highlighted
        self.maps_gray = gray

    def summary_lines(self) -> list[str]:
        elapsed = self.elapsed_seconds
        return [
            f"Обработано карт: {self.maps_processed}",
            f"Успешных карт: {self.maps_succeeded}",
            f"Orb of Scouring: {self.scouring_used}",
            f"Orb of Alchemy: {self.alchemy_used}",
            f"Итераций крафта: {self.craft_iterations}",
            f"Время: {elapsed:.1f} с",
        ]