from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .config import PROJECT_ROOT, AppConfig, RegionRatios
from .window_utils import GameWindow, ScreenCapture, ScreenRect, iter_grid_cells, ratios_to_rect


@dataclass(frozen=True)
class GridCalibration:
    first_center_client: tuple[int, int]
    last_center_client: tuple[int, int]
    columns: int
    rows: int


def region_from_grid_centers(
    client_size: ScreenRect,
    calibration: GridCalibration,
) -> RegionRatios:
    cx0, cy0 = calibration.first_center_client
    cx1, cy1 = calibration.last_center_client
    cols = calibration.columns
    rows = calibration.rows

    if cols < 1 or rows < 1:
        raise ValueError("Сетка должна иметь хотя бы 1 строку и 1 столбец")

    if cols == 1:
        cell_w = 50.0
    else:
        cell_w = (cx1 - cx0) / (cols - 1)

    if rows == 1:
        cell_h = 50.0
    else:
        cell_h = (cy1 - cy0) / (rows - 1)

    if cell_w <= 1 or cell_h <= 1:
        raise ValueError(
            "Точки слишком близко. Наводите на центр первой и последней ячейки сетки."
        )

    left = cx0 - cell_w / 2.0
    top = cy0 - cell_h / 2.0
    width = cell_w * cols
    height = cell_h * rows

    cw = max(1, client_size.width)
    ch = max(1, client_size.height)

    return RegionRatios(
        left=max(0.0, min(0.98, left / cw)),
        top=max(0.0, min(0.98, top / ch)),
        width=max(0.02, min(1.0, width / cw)),
        height=max(0.02, min(1.0, height / ch)),
        columns=cols,
        rows=rows,
    )


def draw_region_grid(
    frame: np.ndarray,
    region: ScreenRect,
    columns: int,
    rows: int,
    color: tuple[int, int, int],
    label: str,
) -> None:
    cells = iter_grid_cells(region, columns, rows)
    for cell in cells:
        cv2.rectangle(
            frame,
            (cell.left, cell.top),
            (max(cell.left, cell.right - 1), max(cell.top, cell.bottom - 1)),
            color,
            1,
        )
    cv2.putText(
        frame,
        label,
        (region.left + 4, max(16, region.top - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        1,
        cv2.LINE_AA,
    )


def save_layout_debug_image(
    window: GameWindow,
    capture: ScreenCapture,
    config: AppConfig,
    output_dir: Path | None = None,
) -> Path:
    out_dir = output_dir or (PROJECT_ROOT / "debug")
    out_dir.mkdir(parents=True, exist_ok=True)

    frame = capture.capture_client(window)
    client = window.client_rect

    stash = ratios_to_rect(client, config.stash)
    inventory = ratios_to_rect(client, config.inventory)

    draw_region_grid(
        frame,
        stash,
        config.stash.columns,
        config.stash.rows,
        (0, 220, 255),
        "stash",
    )
    draw_region_grid(
        frame,
        inventory,
        config.inventory.columns,
        config.inventory.rows,
        (80, 255, 80),
        "inventory",
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"layout_{stamp}.png"
    cv2.imwrite(str(path), frame)
    return path


def format_region(region: RegionRatios) -> str:
    return (
        f"left={region.left:.4f}, top={region.top:.4f}, "
        f"width={region.width:.4f}, height={region.height:.4f}, "
        f"{region.columns}x{region.rows}"
    )