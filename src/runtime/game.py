"""游戏生命周期服务：启动 / 关闭 / 重启 / 状态，全部同步阻塞。

设计边界（与 P1 计划一致）：

* 只负责「进程是否在跑、能否到达可操作画面、如何关掉」，不关心任何业务弹窗；
* 弹窗只作为等待期的**纠偏**：既没有就绪、也没有登录页时，每
  ``dismiss_interval`` 秒给弹窗层一次机会（可选依赖，没接就纯等）；
* 每款游戏的差异（包名、登录页锚点、大厅锚点、点击方式）由
  ``GameAdapter`` 提供，本模块不认识任何具体游戏；
* 同一时刻只允许一个生命周期动作（模块级可重入锁），避免启动过程中
  又被「一键日常」或 GUI 按钮触发第二次。
"""

import time
from dataclasses import dataclass, replace
from threading import RLock

from src.games.base import (
    BootstrapConfig,
    BootstrapError,
    BootstrapResult,
    GameAdapter,
)
from src.games.registry import create, profiles

GameStart = BootstrapResult
GameError = BootstrapError

DEFAULT_CONFIRM_HITS = 2
DEFAULT_DISMISS_INTERVAL = 5.0
DEFAULT_MAX_DISMISS = 12
_CONFIRM_GAP = 0.3

_LOCK = RLock()
_FORCE_RESTART: list[bool] = []


@dataclass(frozen=True)
class GameStatus:
    """只读状态快照；``status()`` 不产生任何副作用。"""

    profile: str
    package: str
    running: bool
    ready: bool
    login_screen: bool


class _TaskContext:
    """把 ``BaseTask`` 的能力收窄成适配器需要的那一点接口。"""

    def __init__(self, task, profile='', config=None):
        self.task = task
        self.profile = profile
        self.package = ''
        self._config = config or getattr(getattr(task, 'executor', None), 'config', None) or {}

    @property
    def config(self):
        return self._config

    def find(self, name, threshold=None):
        return self.task.find_one(name, threshold=threshold) if threshold is not None \
            else self.task.find_one(name)

    def next_frame(self):
        """强制刷新一帧，避免用缓存画面判断状态。"""
        try:
            return self.task.next_frame()
        except Exception:  # noqa: BLE001 - 取帧失败按「没有新帧」处理
            return None

    def click(self, x, y):
        return self.task.click(x, y)
    def click_box(self, box):
        return self.task.click(box)

    def screenshot(self, name=None):
        try:
            return self.task.screenshot(name=name)
        except Exception:
            return None

    def sleep(self, seconds):
        self.task.sleep(seconds)

    def log(self, message):
        logger = getattr(self.task, 'log_info', None)
        if callable(logger):
            logger(message)

    def shell(self, command):
        """执行一条 adb shell 命令，失败时记录日志并返回空串。"""
        shell = getattr(self.task, 'adb_shell', None)
        if not callable(shell):
            return ''
        try:
            output = shell(str(command))
        except Exception as exc:  # noqa: BLE001 - 设备异常不打断调用方
            self.log(f'game: shell 失败 {command} -> {exc}')
            return ''
        if not isinstance(output, (str, bytes)):
            return ''
        if isinstance(output, bytes):
            return output.decode('utf-8', 'ignore')
        return '' if output is None else str(output)

    def after_login(self):
        runner = getattr(self.task, 'run_overlays', None)
        if callable(runner):
            runner('after_login')

    def dismiss_overlays(self):
        """等待期的弹窗纠偏；没有接弹窗层时返回 False。"""

        guard = getattr(self.task, 'overlay_guard', None)
        runner = getattr(self.task, 'run_overlays', None)
        if guard is None or not callable(runner):
            return False
        runner('anytime')
        return True


def from_task(task, profile=''):
    """任务上下文：任务执行前的隐式检查用它。"""

    return _TaskContext(task, profile=profile)


def from_app(profile=''):
    """GUI 上下文（P1.3 接入）；当前显式未实现，避免半成品被误用。"""

    raise NotImplementedError('GUI 上下文尚未接入，请在任务里调用或先完成任务执行前检查')


def _config_of(ctx):
    raw = ctx.config.get('game_bootstrap') or {}
    allowed = ('boot_timeout', 'enter_timeout', 'poll_interval', 'force_restart',
               'confirm_hits', 'dismiss_interval', 'max_dismiss')
    values = {key: raw[key] for key in allowed if key in raw}
    return BootstrapConfig(**{k: v for k, v in values.items()
                              if k in ('boot_timeout', 'enter_timeout',
                                       'poll_interval', 'force_restart')}), values


def _profile_of(ctx):
    return (ctx.profile or ctx.config.get('game_profile') or '').strip()


def _adapter(profile):
    adapter = create(profile)
    if adapter is None:
        raise GameError(f'game_profile={profile!r} 没有可用适配器（已注册：{profiles()}）')
    return adapter


def _ready(adapter, ctx, hits=DEFAULT_CONFIRM_HITS):
    """连续 ``hits`` 次命中才算就绪，避免过场动画的最后一帧造成假就绪。"""

    for index in range(max(1, hits)):
        ctx.next_frame()
        if not adapter.is_ready(ctx):
            return False
        if index + 1 < hits:
            ctx.sleep(_CONFIRM_GAP)
    return True


def _wait_until(adapter, ctx, cfg, timeout, phase, on_tick=None):
    """等到「就绪」或「登录页」；返回 ('ready'|'login', elapsed)。"""

    started = time.time()
    deadline = started + timeout
    while time.time() < deadline:
        ctx.next_frame()
        if _ready(adapter, ctx):
            return 'ready', time.time() - started
        if adapter.is_login_screen(ctx):
            return 'login', time.time() - started
        if on_tick is not None:
            on_tick()
        ctx.sleep(cfg.poll_interval)
    ctx.screenshot(f'bootstrap_{phase}_timeout')
    raise GameError(
        f'{phase} 阶段 {timeout:.0f}s 内没有等到登录页或可执行画面'
        f'（profile={ctx.profile}，package={ctx.package}）'
    )


def _wait_ready(adapter, ctx, cfg, timeout, phase, on_tick=None):
    """点完登录之后只等「就绪」：还停在登录页说明点击没生效，继续等。"""

    started = time.time()
    deadline = started + timeout
    while time.time() < deadline:
        ctx.next_frame()
        if _ready(adapter, ctx):
            return time.time() - started
        if on_tick is not None:
            on_tick()
        ctx.sleep(cfg.poll_interval)
    ctx.screenshot(f'bootstrap_{phase}_timeout')
    raise GameError(
        f'{phase} 阶段 {timeout:.0f}s 内没有等到可执行画面'
        f'（profile={ctx.profile}，package={ctx.package}）'
    )


def start(ctx=None, *, task=None, tap_login=True, timeout=None, profile='',
          force_restart=None):
    """把游戏带到可操作画面，返回本次做了什么。

    Args:
        ctx: 已构造的上下文；与 ``task`` 二选一。
        task: 传入任务对象时自动包装上下文。
        tap_login: 停在登录页时是否顺手点进去。
        timeout: 覆盖配置里的 ``boot_timeout``。
        profile: 覆盖配置里的 ``game_profile``。

    Raises:
        GameError: profile 未注册、超时、点击无效。
    """

    ctx = ctx or from_task(task, profile=profile)
    if profile and not ctx.profile:
        ctx.profile = profile
    if force_restart is not None:
        _FORCE_RESTART.append(bool(force_restart))

    with _LOCK:
        name = _profile_of(ctx)
        if not name:
            ctx.log('bootstrap: 未配置 game_profile，跳过启动层')
            return GameStart.SKIPPED
        ctx.profile = name

        adapter = _adapter(name)
        ctx.package = getattr(adapter, 'package_name', '') or ''
        cfg, raw = _config_of(ctx)
        if _FORCE_RESTART:
            cfg = replace(cfg, force_restart=_FORCE_RESTART.pop())
        confirm = int(raw.get('confirm_hits', DEFAULT_CONFIRM_HITS))
        dismiss_interval = float(raw.get('dismiss_interval', DEFAULT_DISMISS_INTERVAL))
        max_dismiss = int(raw.get('max_dismiss', DEFAULT_MAX_DISMISS))

        if cfg.force_restart:
            stop_hook = getattr(adapter, 'stop', None)
            if callable(stop_hook):
                ctx.log(f'bootstrap: force_restart=true，先关闭 {adapter.name}')
                stop_hook(ctx)
                ctx.sleep(1.0)
            cfg = replace(cfg, force_restart=False)

        if _ready(adapter, ctx, confirm):
            ctx.log(f'bootstrap: 已在可操作画面（{adapter.name}）')
            return GameStart.ALREADY_READY

        did_launch = False
        did_tap = False

        dismiss_at = 0.0
        dismiss_count = 0

        def tick():
            nonlocal dismiss_at, dismiss_count
            now = time.time()
            if dismiss_count >= max_dismiss or now - dismiss_at < dismiss_interval:
                return
            dismiss_at = now
            if ctx.dismiss_overlays():
                dismiss_count += 1
                ctx.log(f'bootstrap: 等待期间尝试关闭弹窗（{dismiss_count}/{max_dismiss}）')

        if adapter.is_login_screen(ctx):
            if not tap_login:
                ctx.log(f'bootstrap: 停在登录页，按参数不点击（{adapter.name}）')
            elif not adapter.tap_login(ctx):
                ctx.screenshot('bootstrap_tap_failed')
                raise GameError('登录页存在但点击没有发出')
            else:
                did_tap = True
                ctx.log(f'bootstrap: 已点击登录页（{adapter.name}）')
            elapsed = _wait_ready(adapter, ctx, cfg, cfg.enter_timeout, 'login', tick)
        else:
            stop_hook = getattr(adapter, 'stop', None)
            if cfg.force_restart and callable(stop_hook):
                ctx.log(f'bootstrap: force_restart=true，先关闭 {adapter.name}')
                stop_hook(ctx)
            ctx.log(f'bootstrap: 启动 {adapter.name}（{ctx.package}）')
            adapter.launch(ctx)
            ctx.sleep(2.0)
            did_launch = True
            phase, elapsed = _wait_until(
                adapter, ctx, cfg, timeout or cfg.boot_timeout, 'launch', tick)
            if phase == 'login':
                if tap_login and not adapter.tap_login(ctx):
                    ctx.screenshot('bootstrap_tap_failed')
                    raise GameError('登录页存在但点击没有发出')
                did_tap = True
                phase, elapsed = _wait_until(
                    adapter, ctx, cfg, cfg.enter_timeout, 'login', tick)

        ctx.after_login()
        result = GameStart.LAUNCHED if did_launch else GameStart.TAPPED
        ctx.log(f'bootstrap: 已进入游戏，结果={result.value}（{elapsed:.1f}s）')
        return result


def stop(ctx=None, *, task=None, profile=''):
    """关闭游戏；返回是否确认已经关闭。"""

    ctx = ctx or from_task(task)

    with _LOCK:
        name = (profile or _profile_of(ctx)).strip()
        if not name:
            return False
        adapter = _adapter(name)
        ctx.profile = name
        ctx.package = getattr(adapter, 'package_name', '') or ''

        stop_hook = getattr(adapter, 'stop', None)
        if callable(stop_hook):
            stop_hook(ctx)
        elif ctx.package:
            ctx.shell(f'am force-stop {ctx.package}')

        ctx.sleep(1.0)
        running = _is_running(ctx, adapter)
        if running and ctx.package:
            ctx.log(f'game: 关闭 {name} 未生效，重试 force-stop')
            ctx.shell(f'am force-stop {ctx.package}')
            ctx.sleep(1.0)
            running = _is_running(ctx, adapter)
        ctx.log(f'game: 关闭 {name} → running={running}')
        return not running


def restart(ctx=None, *, task=None, tap_login=True, timeout=None, profile=''):
    """先关闭再启动，返回 ``start()`` 的结果。"""

    stop(ctx=ctx, task=task, profile=profile)
    return start(ctx=ctx, task=task, tap_login=tap_login, timeout=timeout, profile=profile)


def status(ctx=None, *, task=None):
    """只读状态快照，不启动、不点击、不截图。"""

    ctx = ctx or from_task(task)
    name = _profile_of(ctx)
    if not name:
        return GameStatus(profile='', package='', running=False,
                          ready=False, login_screen=False)
    adapter = _adapter(name)
    ctx.profile = name
    ctx.package = getattr(adapter, 'package_name', '') or ''
    return GameStatus(
        profile=name,
        package=ctx.package,
        running=_is_running(ctx, adapter),
        ready=bool(adapter.is_ready(ctx)),
        login_screen=bool(adapter.is_login_screen(ctx)),
    )


def _is_running(ctx, adapter):
    """优先问适配器；否则用 ``pidof`` 推断。"""

    probe = getattr(adapter, 'is_running', None)
    if callable(probe):
        return bool(probe(ctx))
    if not ctx.package:
        return False
    output = ctx.shell(f'pidof {ctx.package}')
    return bool((output or '').strip())
