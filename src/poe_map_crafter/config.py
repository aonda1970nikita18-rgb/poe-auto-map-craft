from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .currency_layout import screenshot_currency_layout

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default_config.json"


@dataclass
class RegionRatios:
    left: float
    top: float
    width: float
    height: float
    columns: int = 1
    rows: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "columns": self.columns,
            "rows": self.rows,
        }


@dataclass
class AppConfig:
    window_title_substrings: list[str] = field(default_factory=lambda: ["Path of Exile"])
    stash: RegionRatios = field(
        default_factory=lambda: RegionRatios(0.08, 0.12, 0.42, 0.62, 12, 12)
    )
    inventory: RegionRatios = field(
        default_factory=lambda: RegionRatios(0.52, 0.45, 0.38, 0.48, 12, 5)
    )
    search_bar: RegionRatios = field(
        default_factory=lambda: RegionRatios(0.08, 0.08, 0.25, 0.03, 1, 1)
    )
    currency_mode: str = "probe"
    currency_slots: dict[str, tuple[int, int] | None] = field(
        default_factory=lambda: {"scouring": None, "alchemy": None}
    )
    fixed_currency_slots: dict[str, list[tuple[int, int, int]]] = field(
        default_factory=screenshot_currency_layout
    )
    detection: dict[str, float] = field(default_factory=dict)
    delays_ms: dict[str, int] = field(default_factory=lambda: {"min": 150, "max": 350})
    click_jitter_px: dict[str, int] = field(default_factory=lambda: {"min": 1, "max": 4})
    currency_stack_fallback: dict[str, int | bool] = field(
        default_factory=lambda: {
            "scouring": 30,
            "alchemy": 20,
            "use_when_unread": True,
        }
    )
    inventory_probe: dict[str, int | bool] = field(
        default_factory=lambda: {
            "enabled": True,
            "hover_wait_ms": 320,
            "tooltip_offset_x": 20,
            "tooltip_offset_y": -140,
            "tooltip_width": 450,
            "tooltip_height": 240,
        }
    )
    stash_recheck_delays_ms: list[int] = field(default_factory=lambda: [0, 80, 160])
    action_wait_after_currency_ms: int = 350
    action_wait_after_craft_ms: int = 100
    emergency_hotkey: str = "f12"
    release_cursor_on_stop: bool = True
    release_cursor_escape_presses: int = 2
    run_validation_on_first_map: bool = True
    max_craft_iterations_per_map: int = 200
    pyautogui_pause: float = 0.05

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        config_path = path or DEFAULT_CONFIG_PATH
        with config_path.open(encoding="utf-8") as fp:
            raw = json.load(fp)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AppConfig:
        stash = RegionRatios(**raw["stash"])
        inventory = RegionRatios(**raw["inventory"])
        search_bar = RegionRatios(**raw["search_bar"])
        slots = raw.get("currency_slots", {})
        currency_slots: dict[str, tuple[int, int] | None] = {
            "scouring": _slot(slots.get("scouring")),
            "alchemy": _slot(slots.get("alchemy")),
        }
        fixed_raw = raw.get("fixed_currency_slots")
        fixed_currency_slots = _parse_fixed_currency_stacks(
            fixed_raw, stack_fb := dict(
                raw.get(
                    "currency_stack_fallback",
                    {"scouring": 30, "alchemy": 20, "use_when_unread": True},
                )
            )
        )
        currency_mode = str(raw.get("currency_mode", "probe"))
        if currency_mode not in ("probe", "fixed"):
            currency_mode = "probe"
        delays = raw.get("delays_ms", {"min": 150, "max": 350})
        jitter = raw.get("click_jitter_px", {"min": 1, "max": 4})
        stack_fb = dict(
            raw.get(
                "currency_stack_fallback",
                {"scouring": 30, "alchemy": 20, "use_when_unread": True},
            )
        )
        inventory_probe = dict(
            raw.get(
                "inventory_probe",
                {
                    "enabled": True,
                    "hover_wait_ms": 320,
                    "tooltip_offset_x": 20,
                    "tooltip_offset_y": -140,
                    "tooltip_width": 450,
                    "tooltip_height": 240,
                },
            )
        )
        return cls(
            window_title_substrings=list(raw.get("window_title_substrings", ["Path of Exile"])),
            stash=stash,
            inventory=inventory,
            search_bar=search_bar,
            currency_mode=currency_mode,
            currency_slots=currency_slots,
            fixed_currency_slots=fixed_currency_slots,
            detection=dict(raw.get("detection", {})),
            delays_ms={"min": int(delays["min"]), "max": int(delays["max"])},
            click_jitter_px={"min": int(jitter["min"]), "max": int(jitter["max"])},
            currency_stack_fallback={
                "scouring": int(stack_fb.get("scouring", 30)),
                "alchemy": int(stack_fb.get("alchemy", 20)),
                "use_when_unread": bool(stack_fb.get("use_when_unread", True)),
            },
            inventory_probe=inventory_probe,
            stash_recheck_delays_ms=[
                int(x) for x in raw.get("stash_recheck_delays_ms", [0, 80, 160])
            ],
            action_wait_after_currency_ms=int(raw.get("action_wait_after_currency_ms", 350)),
            action_wait_after_craft_ms=int(raw.get("action_wait_after_craft_ms", 100)),
            emergency_hotkey=str(raw.get("emergency_hotkey", "f12")),
            release_cursor_on_stop=bool(raw.get("release_cursor_on_stop", True)),
            release_cursor_escape_presses=int(raw.get("release_cursor_escape_presses", 2)),
            run_validation_on_first_map=bool(raw.get("run_validation_on_first_map", True)),
            max_craft_iterations_per_map=int(raw.get("max_craft_iterations_per_map", 200)),
            pyautogui_pause=float(raw.get("pyautogui_pause", 0.05)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_title_substrings": self.window_title_substrings,
            "stash": self.stash.to_dict(),
            "inventory": self.inventory.to_dict(),
            "search_bar": {
                "left": self.search_bar.left,
                "top": self.search_bar.top,
                "width": self.search_bar.width,
                "height": self.search_bar.height,
            },
            "currency_mode": self.currency_mode,
            "currency_slots": {
                "scouring": list(self.currency_slots["scouring"])
                if self.currency_slots["scouring"]
                else None,
                "alchemy": list(self.currency_slots["alchemy"])
                if self.currency_slots["alchemy"]
                else None,
            },
            "fixed_currency_slots": {
                "scouring": [[c, r, n] for c, r, n in self.fixed_currency_slots["scouring"]],
                "alchemy": [[c, r, n] for c, r, n in self.fixed_currency_slots["alchemy"]],
            },
            "detection": deepcopy(self.detection),
            "delays_ms": deepcopy(self.delays_ms),
            "click_jitter_px": deepcopy(self.click_jitter_px),
            "currency_stack_fallback": deepcopy(self.currency_stack_fallback),
            "inventory_probe": deepcopy(self.inventory_probe),
            "stash_recheck_delays_ms": list(self.stash_recheck_delays_ms),
            "action_wait_after_currency_ms": self.action_wait_after_currency_ms,
            "action_wait_after_craft_ms": self.action_wait_after_craft_ms,
            "emergency_hotkey": self.emergency_hotkey,
            "release_cursor_on_stop": self.release_cursor_on_stop,
            "release_cursor_escape_presses": self.release_cursor_escape_presses,
            "run_validation_on_first_map": self.run_validation_on_first_map,
            "max_craft_iterations_per_map": self.max_craft_iterations_per_map,
            "pyautogui_pause": self.pyautogui_pause,
        }

    def sync_currency_mode(self) -> None:
        if self.currency_mode == "fixed":
            sc = self.fixed_currency_slots.get("scouring") or [(0, 0, 30)]
            al = self.fixed_currency_slots.get("alchemy") or [(5, 0, 20)]
            self.currency_slots = {
                "scouring": (sc[0][0], sc[0][1]),
                "alchemy": (al[0][0], al[0][1]),
            }
        else:
            self.currency_slots = {"scouring": None, "alchemy": None}

    def save(self, path: Path | None = None) -> None:
        config_path = path or DEFAULT_CONFIG_PATH
        with config_path.open("w", encoding="utf-8") as fp:
            json.dump(self.to_dict(), fp, indent=2, ensure_ascii=False)


def _slot(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    return None


def _parse_fixed_currency_stacks(
    fixed_raw: Any,
    stack_fb: dict[str, int | bool],
) -> dict[str, list[tuple[int, int, int]]]:
    default = screenshot_currency_layout()
    if not isinstance(fixed_raw, dict):
        return default

    out: dict[str, list[tuple[int, int, int]]] = {}
    for kind, fb_key in (("scouring", "scouring"), ("alchemy", "alchemy")):
        default_stack = int(stack_fb.get(fb_key, 30 if kind == "scouring" else 20))
        raw_kind = fixed_raw.get(kind)
        if raw_kind is None:
            out[kind] = list(default[kind])
            continue
        if isinstance(raw_kind, (list, tuple)) and raw_kind and isinstance(raw_kind[0], (int, float)):
            if len(raw_kind) == 2:
                out[kind] = [(int(raw_kind[0]), int(raw_kind[1]), default_stack)]
                continue
            if len(raw_kind) == 3:
                out[kind] = [(int(raw_kind[0]), int(raw_kind[1]), int(raw_kind[2]))]
                continue
        stacks: list[tuple[int, int, int]] = []
        if isinstance(raw_kind, list):
            for item in raw_kind:
                if not isinstance(item, (list, tuple)):
                    continue
                if len(item) == 2:
                    stacks.append((int(item[0]), int(item[1]), default_stack))
                elif len(item) >= 3:
                    stacks.append((int(item[0]), int(item[1]), int(item[2])))
        out[kind] = stacks if stacks else list(default[kind])
    return out