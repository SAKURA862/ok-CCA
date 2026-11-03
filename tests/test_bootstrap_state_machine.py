"""启动层状态机自检（不依赖 pytest，直接 python 运行）。

覆盖计划里 P1 的行为矩阵：
已就绪 / 未运行 / 停在登录页 / 加载页超时 / 点击无效 / 未配置 profile /
profile 未注册，以及 ``MyBaseTask`` 的包装是否只执行一次、``run`` 是否仍是
同步普通函数（MCP 的校验依赖这一点）。
"""

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.games import base as game_base
from src.tasks import bootstrap
from src.tasks.MyBaseTask import MyBaseTask


class FakeTask:
    """够用的假任务：只实现启动层会碰到的接口。"""

    game_profile = ''
    SKIP_GAME_BOOTSTRAP = False

    def __init__(self, config=None):
        config = config or {}
        self.game_profile = config.get('game_profile', '')
        self.logs = []
        self.shots = []
        self.executor = type('E', (), {'config': config})()

    def log_info(self, message, *args, **kwargs):
        self.logs.append(message)

    def sleep(self, seconds):
        time.sleep(min(seconds, 0.01))

    def screenshot(self, name=None, **kwargs):
        self.shots.append(name)
        return f'/tmp/{name}.png'


class FakeAdapter:
    """可编排的假适配器：用布尔量模拟画面变化。"""

    name = 'fake'
    package_name = 'com.example.fake'

    def __init__(self, ready=False, login=False, enters_game=True, launch_helps=True):
        self.ready = ready
        self.login = login
        self.enters_game = enters_game
        self.launch_helps = launch_helps
        self.launched = 0
        self.tapped = 0

    def launch(self, task):
        self.launched += 1
        if self.launch_helps:
            self.login = True

    def is_login_screen(self, task):
        return self.login

    def is_ready(self, task):
        return self.ready

    def tap_login(self, task):
        self.tapped += 1
        if self.enters_game:
            self.login = False
            self.ready = True
        return True


FAILED = []


def check(name, fn):
    try:
        fn()
    except AssertionError as exc:
        FAILED.append(f'{name}: {exc}')
        print(f'FAIL {name}: {exc}')
    except Exception:
        FAILED.append(f'{name}: {traceback.format_exc()}')
        print(f'ERROR {name}')
        traceback.print_exc()
    else:
        print(f'PASS {name}')


def _patch(adapter):
    """绕过 registry 的文件导入，直接把实例塞给 bootstrap.create。"""
    original = bootstrap.create
    bootstrap.create = lambda profile: adapter if profile == 'fake' else original(profile)
    return original


def case_already_ready():
    adapter = FakeAdapter(ready=True)
    restore = _patch(adapter)
    try:
        task = FakeTask({'game_profile': 'fake'})
        result = bootstrap.ensure_ready(task)
    finally:
        bootstrap.create = restore
    assert result is game_base.BootstrapResult.ALREADY_READY, result
    assert adapter.launched == 0, '已就绪却又拉起了进程'
    assert adapter.tapped == 0


def case_launch_then_tap():
    adapter = FakeAdapter(ready=False, login=False)
    restore = _patch(adapter)
    try:
        task = FakeTask({'game_profile': 'fake'})
        result = bootstrap.ensure_ready(task)
    finally:
        bootstrap.create = restore
    assert result is game_base.BootstrapResult.LAUNCHED, result
    assert adapter.launched == 1, f'launch 次数应为 1，实际 {adapter.launched}'
    assert adapter.tapped == 1, f'tap 次数应为 1，实际 {adapter.tapped}'


def case_already_running_at_login():
    adapter = FakeAdapter(ready=False, login=True)
    restore = _patch(adapter)
    try:
        task = FakeTask({'game_profile': 'fake'})
        result = bootstrap.ensure_ready(task)
    finally:
        bootstrap.create = restore
    assert result is game_base.BootstrapResult.TAPPED, result
    assert adapter.launched == 0, '停在登录页时不应重启进程'


def case_loading_until_timeout():
    adapter = FakeAdapter(ready=False, login=False, launch_helps=False)
    restore = _patch(adapter)
    try:
        task = FakeTask({'game_profile': 'fake',
                         'game_bootstrap': {'boot_timeout': 0.3, 'poll_interval': 0.02}})
        try:
            bootstrap.ensure_ready(task)
        except game_base.BootstrapError as exc:
            assert '可执行画面' in str(exc), str(exc)
        else:
            raise AssertionError('加载页超时没有抛 BootstrapError')
    finally:
        bootstrap.create = restore
    assert task.shots, '超时失败必须留下截图'


def case_tap_has_no_effect():
    adapter = FakeAdapter(ready=False, login=True, enters_game=False)
    restore = _patch(adapter)
    try:
        task = FakeTask({'game_profile': 'fake',
                         'game_bootstrap': {'enter_timeout': 0.3, 'poll_interval': 0.02}})
        try:
            bootstrap.ensure_ready(task)
        except game_base.BootstrapError as exc:
            assert '可执行画面' in str(exc), str(exc)
        else:
            raise AssertionError('点击无效时没有抛错')
    finally:
        bootstrap.create = restore
    assert task.shots, '点击无效时必须留下截图'


def case_no_profile():
    adapter = FakeAdapter()
    restore = _patch(adapter)
    try:
        task = FakeTask({})
        result = bootstrap.ensure_ready(task)
    finally:
        bootstrap.create = restore
    assert result is game_base.BootstrapResult.SKIPPED, result
    assert adapter.launched == 0


def case_unknown_profile():
    task = FakeTask({'game_profile': 'does-not-exist'})
    try:
        bootstrap.ensure_ready(task)
    except game_base.BootstrapError as exc:
        assert 'does-not-exist' in str(exc), str(exc)
    else:
        raise AssertionError('未注册的 profile 应该报错，而不是静默跳过')


def case_task_wrapper_runs_once():
    calls = []

    class WrappedTask(MyBaseTask):
        game_profile = ''

        def run(self):
            calls.append('run')
            return 'ok'

    assert getattr(WrappedTask.run, '_game_bootstrap_wrapped', False), 'run 没有被包装'
    assert WrappedTask.run is not MyBaseTask.__mro__[1].run, 'run 仍是 BaseTask.run'

    task = WrappedTask.__new__(WrappedTask)  # 跳过 BaseTask.__init__ 的依赖
    task._bootstrap_done = False
    task.__dict__['_executor'] = type('E', (), {'config': {}})()
    task.game_profile = ''
    task.SKIP_GAME_BOOTSTRAP = False
    task.log_info = lambda *a, **k: None
    assert task.run() == 'ok'
    assert calls == ['run'], calls
    assert task.ensure_game_ready() is None


def case_skip_flag():
    """SKIP_GAME_BOOTSTRAP=True 时，即便配了 profile 也不应触碰适配器。"""
    calls = []

    class SkippingTask(MyBaseTask):
        game_profile = 'fake'
        SKIP_GAME_BOOTSTRAP = True

        def run(self):
            calls.append('run')

    original = bootstrap.ensure_ready

    def boom(task):
        raise AssertionError('SKIP_GAME_BOOTSTRAP 生效时不应调用 ensure_ready')

    bootstrap.ensure_ready = boom
    try:
        task = SkippingTask.__new__(SkippingTask)
        task._bootstrap_done = False
        task.__dict__['_executor'] = type('E', (), {'config': {}})()
        task.log_info = lambda *a, **k: None
        task.run()
    finally:
        bootstrap.ensure_ready = original
    assert calls == ['run'], calls


def main():
    check('already_ready', case_already_ready)
    check('launch_then_tap', case_launch_then_tap)
    check('already_running_at_login', case_already_running_at_login)
    check('loading_until_timeout', case_loading_until_timeout)
    check('tap_has_no_effect', case_tap_has_no_effect)
    check('no_profile', case_no_profile)
    check('unknown_profile', case_unknown_profile)
    check('task_wrapper_runs_once', case_task_wrapper_runs_once)
    check('skip_flag', case_skip_flag)
    if FAILED:
        print(f'\n{len(FAILED)} case(s) failed')
        return 1
    print('\nall cases passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
