"""Shared startup logic for the Cross Core (交错战线) tasks.

The launcher is not a task of its own: it is called by tasks that need the game
to be running (for example the one-click daily task). It only uses ok-script
capture/interaction APIs, geometry and colour classification, so it can run
head-less through the MCP runner or from the GUI scheduler.
"""

from __future__ import annotations

import time

import numpy as np
from PIL import Image

from ok import og
from ok.util.logger import Logger

logger = Logger.get_logger(__name__)

PACKAGE_NAME = "com.megagame.crosscore"

# The "开始游戏" button is a bright, horizontally centred band in the lower half
# of the title screen. Ratios are relative to the captured frame.
TITLE_ROI = (0.33, 0.60, 0.67, 0.73)
TITLE_MIN_RATIO = 0.008
TITLE_MAX_RATIO = 0.090
TITLE_MIN_ROWS = 3
TITLE_CENTER_TOLERANCE = 0.08
BLOCK_ROWS = 12

BOOT_TIMEOUT = 180.0
ENTER_TIMEOUT = 90.0
POLL_INTERVAL = 0.6
LEAVE_CONFIRM_SAMPLES = 5


def _frame_image(task):
    frame = task.frame
    if frame is None:
        return None
    if hasattr(frame, "convert"):
        return frame.convert("RGB")
    return Image.fromarray(np.asarray(frame)).convert("RGB")


def _grab(task):
    """Force a fresh capture; MCP runs do not refresh the frame by themselves."""
    try:
        task.next_frame()
    except Exception as exc:  # pragma: no cover - capture hiccups
        logger.warning(f"crosscore launcher: next_frame failed: {exc}")
    return _frame_image(task)


def _bright_mask(image):
    small = image.resize((320, 180))
    arr = np.asarray(small).astype(int)
    red, green, blue = arr[..., 0], arr[..., 1], arr[..., 2]
    return (red > 185) & (green > 185) & (blue > 175)


def title_signature(task):
    """Return ``(found, (cx, cy))`` for the 开始游戏 button in the current frame.

    ``cx``/``cy`` are normalised frame coordinates of the bright band centroid.
    """
    image = _grab(task)
    if image is None:
        return False, (0.5, 0.67)
    mask = _bright_mask(image)
    height, width = mask.shape
    x0, y0 = int(TITLE_ROI[0] * width), int(TITLE_ROI[1] * height)
    x1, y1 = int(TITLE_ROI[2] * width), int(TITLE_ROI[3] * height)
    roi = mask[y0:y1, x0:x1]
    ratio = float(roi.mean())
    if ratio < TITLE_MIN_RATIO or ratio > TITLE_MAX_RATIO:
        return False, (0.5, 0.67)
    rows = int((roi.sum(axis=1) > 6).sum())
    if rows < TITLE_MIN_ROWS:
        return False, (0.5, 0.67)
    ys, xs = np.nonzero(roi)
    if len(xs) == 0:
        return False, (0.5, 0.67)
    cx = (xs.mean() + x0) / width
    cy = (ys.mean() + y0) / height
    if abs(cx - 0.5) > TITLE_CENTER_TOLERANCE:
        return False, (cx, cy)
    return True, (cx, cy)


def in_game(task):
    """True when the title screen is gone but the game is still focused."""
    if _foreground_package() != PACKAGE_NAME:
        return False
    found, _ = title_signature(task)
    return not found


def _foreground_package():
    try:
        device = og.device_manager.device
        if device is None:
            return None
        return device.app_current().package
    except Exception as exc:  # pragma: no cover - device hiccups
        logger.warning(f"crosscore launcher: foreground query failed: {exc}")
        return None


def _artifact_dir(task):
    return getattr(task, "artifact_directory", None)


def save_evidence(task, name, note=""):
    """Save the current frame next to the run artifacts when available."""
    try:
        task.screenshot(name)
        logger.info(f"crosscore launcher: saved screenshot {name} {note}".strip())
    except Exception as exc:  # pragma: no cover - screenshot is best effort
        logger.warning(f"crosscore launcher: screenshot {name} failed: {exc}")


def reset_to_start(task):
    """Close the game and return to the emulator home screen."""
    logger.info("crosscore launcher: reset -> close game and go home")
    try:
        task.adb_shell(f"am force-stop {PACKAGE_NAME}")
    except Exception as exc:
        logger.warning(f"crosscore launcher: force-stop failed: {exc}")
    deadline = time.time() + 15
    while time.time() < deadline:
        if _foreground_package() != PACKAGE_NAME:
            break
        time.sleep(0.5)
    try:
        task.adb_shell("input keyevent KEYCODE_HOME")
    except Exception as exc:
        logger.warning(f"crosscore launcher: keyevent HOME failed: {exc}")
    time.sleep(1.5)
    save_evidence(task, "reset_home")


def verify_start_state(task):
    """Baseline is: emulator reachable and the game not in the foreground."""
    package = _foreground_package()
    if package is None:
        raise RuntimeError("无法读取模拟器前台应用，请确认 MuMu 已连接")
    if package == PACKAGE_NAME:
        raise RuntimeError(f"起始状态不正确：{PACKAGE_NAME} 仍在前台")
    logger.info(f"crosscore launcher: start state ok, foreground={package}")
    return True


def ensure_game_started(task, boot_timeout=BOOT_TIMEOUT, enter_timeout=ENTER_TIMEOUT):
    """Launch the game (if needed), press 开始游戏 and wait until it is gone."""
    package = _foreground_package()
    if package == PACKAGE_NAME:
        found, point = title_signature(task)
        if not found:
            logger.info("crosscore launcher: game already running, skip launch")
            return True
        logger.info("crosscore launcher: title screen already visible")
        return _press_start(task, point, enter_timeout)

    logger.info(f"crosscore launcher: launching {PACKAGE_NAME}")
    og.device_manager.adb_start_package(PACKAGE_NAME)

    deadline = time.time() + boot_timeout
    point = None
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        if _foreground_package() != PACKAGE_NAME:
            continue
        found, candidate = title_signature(task)
        if found:
            point = candidate
            logger.info(f"crosscore launcher: 开始游戏 detected at ({point[0]:.3f}, {point[1]:.3f})")
            break
    if point is None:
        save_evidence(task, "failed_no_start_button", f"after {boot_timeout:.0f}s")
        raise RuntimeError(f"{boot_timeout:.0f}s 内没有识别到「开始游戏」按钮")
    return _press_start(task, point, enter_timeout)


def _press_start(task, point, enter_timeout):
    # 按钮固定在画面水平正中、偏下位置；用检测结果只作为「标题页已就绪」的信号，
    # 点击点取几何中心，避免被按钮两侧的装饰横线带偏。
    x = int(task.width * 0.5)
    y = int(task.height * 0.668)
    logger.info(f"crosscore launcher: click 开始游戏 ({x}, {y}), detected at ({point[0]:.3f}, {point[1]:.3f})")
    task.click(x, y)
    task.sleep(1.0)

    gone_samples = 0
    deadline = time.time() + enter_timeout
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        if _foreground_package() != PACKAGE_NAME:
            save_evidence(task, "failed_left_game")
            raise RuntimeError("点击开始游戏后游戏退出了前台")
        found, _ = title_signature(task)
        gone_samples = gone_samples + 1 if not found else 0
        if gone_samples >= LEAVE_CONFIRM_SAMPLES:
            save_evidence(task, "game_entered")
            logger.info("crosscore launcher: title screen dismissed, game is starting")
            return True
    save_evidence(task, "failed_stuck_on_title")
    raise RuntimeError(f"点击开始游戏后 {enter_timeout:.0f}s 内仍停留在标题页")
