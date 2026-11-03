"""项目任务基类：统一挂载「启动层」。

所有任务都继承它，于是无论从 GUI（一键日常 / 详情页单跑）、CLI 还是 MCP
执行，``run()`` 之前都会先过一次 :func:`src.tasks.bootstrap.ensure_ready`。

需要跳过的任务设置 ``SKIP_GAME_BOOTSTRAP = True``；需要指定游戏的任务设置
``game_profile = 'crosscore'``，否则使用 ``config['game_profile']``。
"""

import functools
import time

from ok import BaseTask

from src.runtime import daily, overlay
from src.tasks import bootstrap


class MyBaseTask(BaseTask):
    """项目内所有任务的基类。"""

    # 空字符串 = 不接管启动层，等价于旧行为
    game_profile = ''
    # 个别任务（例如纯本机计算的工具任务）可以显式跳过
    SKIP_GAME_BOOTSTRAP = False
    # 业务多久没有进展就尝试一次 on_stuck 兜底规则（秒）
    STUCK_AFTER = overlay.DEFAULT_STUCK_AFTER

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bootstrap_done = False
        self._overlay_guard = None
        self._daily_state = None
        self._last_progress = time.monotonic()
        self._last_stuck_check = 0.0

    def __init_subclass__(cls, **kwargs):
        """把子类自己定义的 ``run`` 包一层，前面插入启动层。

        只包装子类 ``__dict__`` 里的 ``run``：继承来的实现已经被包装过，
        没有再包一次的问题；没有定义 ``run`` 的子类保持原样，让 MCP 的
        ``cls.run is BaseTask.run`` 校验照常报错。
        """
        super().__init_subclass__(**kwargs)
        original = cls.__dict__.get('run')
        if original is None or getattr(original, '_game_bootstrap_wrapped', False):
            return

        @functools.wraps(original)
        def run(self, *args, **kwargs):
            self.ensure_game_ready()
            return original(self, *args, **kwargs)

        run._game_bootstrap_wrapped = True
        cls.run = run

    def ensure_game_ready(self):
        """幂等：同一次 run 里重复调用只执行一次。"""
        if self._bootstrap_done or self.SKIP_GAME_BOOTSTRAP:
            return None
        self._bootstrap_done = True
        return bootstrap.ensure_ready(self)

    # ------------------------------------------------------------------ 弹窗层
    @property
    def overlay_guard(self) -> overlay.OverlayGuard:
        """按需构建规则表；规则文件来自 ``config['overlays']['rules_file']``。"""
        if self._overlay_guard is None:
            config = getattr(self.executor, 'config', None) or {}
            settings = config.get('overlays') or {}
            self._overlay_guard = overlay.OverlayGuard(
                overlay.load_rules(settings.get('rules_file')),
                min_interval=float(settings.get('min_interval', overlay.DEFAULT_MIN_INTERVAL)),
            )
        return self._overlay_guard

    @property
    def daily_state(self) -> daily.DailyState:
        if self._daily_state is None:
            self._daily_state = daily.state_of(self)
        return self._daily_state

    def report_progress(self):
        """业务做成了一件事；卡住判定的计时器清零。"""
        self._last_progress = time.monotonic()

    def run_overlays(self, when: str, frame=None):
        """执行某个触发时机下的弹窗规则，返回处理掉的规则 id 或 None。

        ``after_login`` / ``on_home`` 时会附带每日规则（每天只跑一次）。
        """
        state = self.daily_state
        pending = when in ('after_login', 'on_home') and state.is_pending()
        handled = self.overlay_guard.process(
            self,
            self.frame if frame is None else frame,
            when=when,
            daily_pending=pending,
        )
        if handled is not None:
            self.report_progress()
        if pending:
            # 无论有没有命中，今天这一组只查一次，避免每帧都做重匹配
            state.mark_done()
        return handled

    def next_frame(self):
        """取新帧的同时过一遍弹窗规则，并做卡住兜底。"""
        frame = super().next_frame()
        self.run_overlays('anytime', frame=frame)
        self._check_stuck(frame)
        return frame

    def _check_stuck(self, frame):
        """业务长时间没有进展时，试一次 on_stuck 规则。"""
        now = time.monotonic()
        if now - self._last_progress < self.STUCK_AFTER:
            return
        if now - self._last_stuck_check < self.STUCK_AFTER:
            return
        self._last_stuck_check = now
        if self.run_overlays('on_stuck', frame=frame) is not None:
            self.report_progress()
