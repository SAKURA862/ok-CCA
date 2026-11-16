"""项目任务基类：在 ``run()`` 前挂启动层，并提供弹窗层与导航层入口。"""

import functools
import inspect
import time
from contextlib import contextmanager
from pathlib import Path

from ok import BaseTask

from src.flow.flow import DEFAULT_WAIT_TIMEOUT
from src.flow.steps import FlowError
from src.nav.actions import ActionExecutor
from src.nav.locator import Locator
from src.nav.model import NavError
from src.nav.navigator import NavCache, Navigator
from src.nav import registry as nav_registry
from src.runtime import daily, overlay
from src.tasks import bootstrap


class MyBaseTask(BaseTask):
    """项目内所有任务的基类。

    Attributes:
      game_profile: 启动层使用的游戏配置名，空表示不接管启动。
      SKIP_GAME_BOOTSTRAP: 为 True 时跳过启动层。
      STUCK_AFTER: 业务多久无进展后尝试 on_stuck 弹窗规则（秒）。
      entry_page: 任务入口页，批量调度时先导航到这里。
      home_page: 任务结束后建议回到的页面。
      nav_profile: 导航图配置名，空表示跟随 ``game_profile``。
    """

    # 空字符串 = 不接管启动层，等价于旧行为
    game_profile = ''
    # 个别任务（例如纯本机计算的工具任务）可以显式跳过
    SKIP_GAME_BOOTSTRAP = False
    # 业务多久没有进展就尝试一次 on_stuck 兜底规则（秒）
    STUCK_AFTER = overlay.DEFAULT_STUCK_AFTER
    # 任务入口页：批量调度时先 goto 到这里，空表示从当前页开始
    entry_page = ''
    # 任务结束后建议回到的页面，空表示不处理
    home_page = ''
    # 导航图 profile，空表示跟随 game_profile
    nav_profile = ''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bootstrap_done = False
        self._overlay_guard = None
        self._daily_state = None
        self._last_progress = time.monotonic()
        self._last_stuck_check = 0.0
        self._locator = None
        self._navigator = None
        # 调用栈深度：任务调用任务的上限控制
        self._call_depth = 0
        # 步骤/状态机之间共享的数据，``Step(call=...)`` 的结果也放这里
        self.data = {}

    def __init_subclass__(cls, **kwargs):
        """包装子类自定义的 ``run``，在真正执行前插入启动层。

        只处理子类 ``__dict__`` 里的 ``run``：继承来的实现已经包过，
        没定义 ``run`` 的子类保持原样，让 MCP 的校验照常报错。
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
        """确保游戏就绪；同一次 run 内只执行一次。"""
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

    # ------------------------------------------------------------------ 导航层
    @property
    def nav_settings(self) -> dict:
        """``config['nav']`` 段，缺省为空字典。"""
        config = getattr(self.executor, 'config', None) or {}
        return config.get('nav') or {}

    @property
    def nav_graph(self):
        """当前任务的页面图。

        Raises:
          NavError: 既没有 ``nav_profile`` 也没有 ``game_profile``。
        """
        profile = self.nav_profile or self.game_profile
        if not profile:
            raise NavError('未配置 game_profile/nav_profile，无法加载导航图')
        return nav_registry.get(profile, self.nav_settings.get('graph_file') or None)

    @property
    def locator(self) -> Locator:
        """页面定位器。"""
        if self._locator is None:
            self._locator = Locator(self.nav_graph, self._find_anchor, warn=self.log_warning)
        return self._locator

    @property
    def navigator(self) -> Navigator:
        """导航执行器。"""
        if self._navigator is None:
            config = getattr(self.executor, 'config', None) or {}
            folder = Path(config.get('config_folder') or 'configs')
            cache_file = self.nav_settings.get('cache_file') or folder / 'nav_cache.json'
            self._navigator = Navigator(
                self.nav_graph,
                locate=self._locate_current,
                wait_page=self._wait_page,
                actions=ActionExecutor(
                    click_template=self._click_nav_template,
                    click_point=lambda x, y: self.click_relative(x, y),
                    press_key=lambda key: self.send_key(key),
                ),
                cache=NavCache.load(cache_file),
                screenshot=lambda name: self.screenshot(name),
                warn=self.log_warning,
                max_hops=int(self.nav_settings.get('max_hops', 6)),
            )
            hint = getattr(self, '_nav_hint', None)
            if hint:
                self._navigator.last_page = hint
        return self._navigator

    def current_page(self) -> str:
        """识别并返回当前页面 id。"""
        return self.navigator.locate()

    def goto(self, page: str, *, attempts: int = 3):
        """导航到指定页面，失败时按返回键退回并重新规划。

        Args:
          page: 目标页面 id。
          attempts: 最多尝试次数。

        Returns:
          实际走过的 ``Path``。
        """
        last: NavError | None = None
        for index in range(1, attempts + 1):
            try:
                return self.navigator.goto(page)
            except NavError as error:
                last = error
                self.log_warning(f'nav: goto {page} 第 {index} 次失败，退回重试: {error}')
                self.back()
                self.sleep(1.0)
                self._locator = None
                self._navigator = None
        raise last

    def ensure_page(self, page: str):
        """确保位于指定页面；已在目标页时不移动。"""
        return self.navigator.ensure(page)

    def nav_back(self) -> str | None:
        """返回上一个停留过的页面。

        与设备返回键 ``back()`` 区分：这里按导航历史回退，不直接按键。
        """
        return self.navigator.back()

    @contextmanager
    def on_page(self, page: str):
        """进入指定页面后执行一段逻辑。

        Args:
          page: 入口页面 id。

        Yields:
          任务自身。
        """
        self.ensure_page(page)
        yield self

    def _find_anchor(self, template: str):
        """用配置的阈值匹配一个锚点模板。"""
        threshold = float(self.nav_settings.get('threshold', 0.8))
        return self.find_one(template, threshold=threshold)

    def _locate_current(self):
        """带 last_page 提示的定位。"""
        last = self._navigator.last_page if self._navigator else None
        return self.locator.locate(last)

    def _wait_page(self, page_id: str, timeout: float) -> bool:
        """等待目标页锚点出现。"""
        settle = float(self.nav_settings.get('settle_time', 0.3))
        return bool(self.wait_until(lambda: self.locator.is_page(page_id),
                                    time_out=timeout, settle_time=settle))

    def _click_nav_template(self, template: str, roi) -> bool:
        """点击模板；未匹配到时返回 False。"""
        box_arg = None
        if roi:
            box_of_screen = getattr(self, 'box_of_screen', None)
            if callable(box_of_screen):
                box_arg = box_of_screen(*roi)
        box = self.find_one(template, box=box_arg,
                            threshold=float(self.nav_settings.get('threshold', 0.8)))
        if box is None:
            return False
        self.click(box)
        return True

    # ------------------------------------------------------------------ 编排层
    def build_flow(self):
        """返回本任务的编排流程。

        Returns:
          ``Flow`` 或 ``StateMachine``；返回 None 表示任务自己实现 ``run()``。
        """
        return None

    def run(self):
        """默认实现：执行 ``build_flow()`` 返回的流程。

        Raises:
          FlowError: 子类既没有实现 ``run()``，也没有实现 ``build_flow()``。
        """
        self.ensure_game_ready()
        flow = self.build_flow()
        if flow is None:
            raise FlowError('任务需要实现 run() 或 build_flow()')
        flow.run(self)

    def click_template(self, template: str) -> bool:
        """点击模板，未匹配到时返回 False。"""
        return self._click_nav_template(template, None)

    def stop_if(self, condition, reason: str = 'stopped') -> None:
        """条件为真时终止流程。

        Args:
          condition: 判断函数，入参是任务；也可以直接传布尔值。
          reason: 终止原因，写入日志与异常消息。

        Raises:
          FlowAborted: 条件为真。
        """
        from src.flow.steps import FlowAborted

        hit = condition(self) if callable(condition) else bool(condition)
        if hit:
            raise FlowAborted(reason)

    @property
    def helper_sources(self):
        """``config['helper_tasks']``：可调用的辅助任务列表。"""
        config = getattr(self.executor, 'config', None) or {}
        return tuple(config.get('helper_tasks') or ())

    def call_task(self, target, **kwargs):
        """同步调用另一个任务，并取回它的返回值。

        Args:
          target: 辅助任务名（见 ``config['helper_tasks']``）或任务类。
          **kwargs: 传给被调用任务 ``execute`` 的参数。

        Returns:
          被调用任务的 ``execute`` 返回值。

        Raises:
          TaskCallError: 调用层数超限、目标无法解析或内层任务抛错。
        """
        from src.runtime import helpers
        from src.runtime.callable import MAX_CALL_DEPTH, TaskCallError

        depth = self._call_depth + 1
        if depth > MAX_CALL_DEPTH:
            raise TaskCallError(f'任务调用层数超过 {MAX_CALL_DEPTH}（{self.name} -> {target}）')
        if isinstance(target, str):
            try:
                cls = helpers.resolve(target, sources=self.helper_sources)
            except LookupError as error:
                raise TaskCallError(str(error)) from error
        elif inspect.isclass(target):
            cls = target
        else:
            raise TaskCallError(f'call_task 需要任务名或任务类，收到 {target!r}')
        name = cls.__name__
        if kwargs and not hasattr(cls, 'bind_params'):
            raise TaskCallError(f'{name} 不是 CallableTask，不能传参 {sorted(kwargs)}')

        inner = cls(executor=self.executor, app=getattr(self, '_app', None))
        inner._call_depth = depth
        inner.data = {}
        inner.result = None
        if kwargs:
            inner.call_params = dict(kwargs)
        if self._navigator is not None:
            inner._nav_hint = self._navigator.last_page
        self.log_info(f'call: {self.name} -> {name} {kwargs or ""}'.strip())
        try:
            inner.run()
        except Exception as error:
            self.screenshot(f'call_failed_{name}')
            raise TaskCallError(f'{self.name} -> {name}: {error}') from error
        finally:
            navigator = inner.__dict__.get('_navigator')
            page = getattr(navigator, 'last_page', '') if navigator is not None else ''
            if page:
                self._nav_hint = page
                if self._navigator is not None:
                    self._navigator.last_page = page
        return inner.result

    def wait_template(self, template: str, timeout: float = DEFAULT_WAIT_TIMEOUT) -> bool:
        """等待模板出现。

        Args:
          template: 模板名。
          timeout: 超时时间（秒）。

        Returns:
          True 表示在超时前匹配到。
        """
        threshold = float(self.nav_settings.get('threshold', 0.8))
        settle = float(self.nav_settings.get('settle_time', 0.3))
        return bool(self.wait_until(
            lambda: self.find_one(template, threshold=threshold) is not None,
            time_out=timeout,
            settle_time=settle,
        ))
