"""启动层：保证游戏在任意任务开始前处于「可执行」状态。

对任务作者只暴露一个函数 :func:`ensure_ready`，由 ``MyBaseTask`` 在 ``run()``
之前自动调用；对游戏作者只暴露 ``src.games.base.GameAdapter`` 协议。

判定顺序（每一步的含义都写死在下面的循环里）：

1. 在登录页 → 点一下，等它进入可执行画面；
2. 已就绪（大厅/主循环）→ 直接放行；
3. 其余情况（未启动、加载中、过场）→ 拉起进程 / 继续等，直到 ``boot_timeout``。
"""

import time

from src.games.base import BootstrapConfig, BootstrapError, BootstrapResult
from src.games.registry import create, profiles

_CONFIG_FIELDS = ('boot_timeout', 'enter_timeout', 'poll_interval', 'force_restart')


def resolve(task) -> tuple[str, BootstrapConfig]:
    """从任务对象与 app config 里读出 profile 名与超时配置。"""
    config = getattr(getattr(task, 'executor', None), 'config', None) or {}
    profile = getattr(task, 'game_profile', '') or config.get('game_profile', '') or ''
    raw = config.get('game_bootstrap') or {}
    values = {key: raw[key] for key in _CONFIG_FIELDS if key in raw}
    return profile.strip(), BootstrapConfig(**values)


def _sleep(task, seconds):
    """优先用任务自带的 sleep（可被 GUI 的停止逻辑打断）。"""
    sleep = getattr(task, 'sleep', None)
    if callable(sleep):
        sleep(seconds)
    else:
        time.sleep(seconds)


def _info(task, message):
    logger = getattr(task, 'log_info', None)
    if callable(logger):
        logger(message)


def _capture(task, name):
    """失败时尽量留下证据截图，截图本身失败不能掩盖原始错误。"""
    shot = getattr(task, 'screenshot', None)
    if not callable(shot):
        return None
    try:
        return shot(name=name)
    except Exception:
        return None


def _wait_ready(task, adapter, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if adapter.is_ready(task):
            return True
        _sleep(task, 0.6)
    _capture(task, 'bootstrap_login_timeout')
    raise BootstrapError(f'点击登录后 {timeout:.0f}s 内没有进入游戏可执行画面')


def ensure_ready(task) -> BootstrapResult:
    """把游戏带到可执行状态，返回本次做了什么。

    Raises:
        BootstrapError: 超时、点击无效或 profile 未注册。
    """
    profile, cfg = resolve(task)
    if not profile:
        _info(task, 'bootstrap: 未配置 game_profile，跳过启动层')
        return BootstrapResult.SKIPPED

    adapter = create(profile)
    if adapter is None:
        raise BootstrapError(f'game_profile={profile!r} 没有注册适配器（已注册：{profiles()}）')

    launched = False
    reset = getattr(adapter, 'reset', None)
    if cfg.force_restart and callable(reset):
        _info(task, f'bootstrap: force_restart=true，先重置 {adapter.name}')
        reset(task)
        launched = True

    deadline = time.time() + cfg.boot_timeout
    while time.time() < deadline:
        if adapter.is_login_screen(task):
            _info(task, f'bootstrap: 检测到登录页，点击进入（{adapter.name}）')
            if not adapter.tap_login(task):
                _capture(task, 'bootstrap_tap_failed')
                raise BootstrapError('登录页存在但点击没有发出')
            _wait_ready(task, adapter, cfg.enter_timeout)
            result = BootstrapResult.LAUNCHED if launched else BootstrapResult.TAPPED
            _info(task, f'bootstrap: 已进入游戏，结果={result.value}')
            return result

        if adapter.is_ready(task):
            result = BootstrapResult.LAUNCHED if launched else BootstrapResult.ALREADY_READY
            _info(task, f'bootstrap: 游戏已就绪，结果={result.value}')
            return result

        if not launched:
            _info(task, f'bootstrap: 启动 {adapter.name}（{adapter.package_name}）')
            adapter.launch(task)
            launched = True

        _sleep(task, cfg.poll_interval)

    _capture(task, 'bootstrap_launch_timeout')
    raise BootstrapError(
        f'{cfg.boot_timeout:.0f}s 内没有等到登录页或可执行画面（profile={profile}，'
        f'launched={launched}）'
    )
