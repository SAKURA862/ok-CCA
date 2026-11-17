"""游戏生命周期服务与批次会话的离线测试。

用假的上下文与适配器覆盖状态机的每条分支，不需要设备、不需要 GUI。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.games.base import BootstrapError, BootstrapResult  # noqa: E402
from src.runtime import game  # noqa: E402
from src.runtime.session import BootstrapSession  # noqa: E402


class FakeCtx:
    """只实现服务真正用到的那几个方法。"""

    def __init__(self, config=None, profile='fake'):
        self.config = config or {}
        self.profile = profile
        self.package = 'com.demo.game'
        self.shots = []
        self.logs = []
        self.shells = []
        self.clicks = []
        self.after_login_calls = 0
        self.dismiss_calls = 0
        self.dismiss_result = False
        self.pidof_output = ''

    def next_frame(self):
        self.frames = getattr(self, 'frames', 0) + 1
        return None

    def find(self, name, threshold=None):
        return None

    def click(self, x, y):
        self.clicks.append((x, y))

    def click_box(self, box):
        self.clicks.append(box)

    def screenshot(self, name=None):
        self.shots.append(name)
        return name

    def sleep(self, seconds):
        return None

    def log(self, message):
        self.logs.append(message)

    def shell(self, command):
        self.shells.append(command)
        if command.startswith('pidof'):
            return self.pidof_output
        return ''

    def after_login(self):
        self.after_login_calls += 1

    def dismiss_overlays(self):
        self.dismiss_calls += 1
        return self.dismiss_result


class FakeAdapter:
    """``ready_after`` / ``login_times`` 控制状态机的走向。"""

    name = 'fake'
    package_name = 'com.demo.game'

    def __init__(self, ready_after=0, login_times=0, tap_ok=True, stop_hook=None,
                 login_after_launch=False):
        self.ready_after = ready_after
        self.login_after_launch = login_after_launch
        self.login_times = login_times
        self.tap_ok = tap_ok
        self.ready_calls = 0
        self.login_calls = 0
        self.launch_calls = 0
        self.tap_calls = 0
        self.stop_calls = 0
        if stop_hook is not None:
            self.stop = stop_hook  # 只有显式提供时才有 stop

    def launch(self, ctx):
        self.launch_calls += 1

    def is_ready(self, ctx):
        self.ready_calls += 1
        return self.ready_calls > self.ready_after

    def is_login_screen(self, ctx):
        self.login_calls += 1
        if self.login_after_launch and not self.launch_calls:
            return False
        return self.login_calls <= self.login_times

    def tap_login(self, ctx):
        self.tap_calls += 1
        return self.tap_ok


def install(monkey, adapter):
    monkey['adapter'] = adapter
    monkey['calls'] = []


def make_config(**bootstrap):
    values = {'boot_timeout': 0.3, 'enter_timeout': 0.2, 'poll_interval': 0.0,
              'confirm_hits': 1}
    values.update(bootstrap)
    return {'game_profile': 'fake', 'game_bootstrap': values}


_current = {}


def fake_create(profile):
    return _current['adapter']


def run(name, func):
    try:
        func()
    except AssertionError:
        print(f'FAIL {name}')
        raise
    print(f'PASS {name}')


def expect_error(exc, func):
    try:
        func()
    except exc as error:
        return error
    raise AssertionError(f'期望 {exc.__name__}，但正常返回')


def case_already_ready():
    adapter = FakeAdapter(ready_after=0)
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config())
    result = game.start(ctx=ctx)
    assert result is BootstrapResult.ALREADY_READY, result
    assert adapter.launch_calls == 0
    assert ctx.after_login_calls == 0


def case_tap_login():
    adapter = FakeAdapter(ready_after=1, login_times=1)
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config())
    result = game.start(ctx=ctx)
    assert result is BootstrapResult.TAPPED, result
    assert adapter.tap_calls == 1
    assert adapter.launch_calls == 0
    assert ctx.after_login_calls == 1


def case_launch_then_tap():
    adapter = FakeAdapter(ready_after=2, login_times=2, login_after_launch=True)
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config())
    result = game.start(ctx=ctx)
    assert result is BootstrapResult.LAUNCHED, result
    assert adapter.launch_calls == 1
    assert adapter.tap_calls >= 1


def case_no_profile():
    _current['adapter'] = FakeAdapter()
    ctx = FakeCtx({'game_profile': '', 'game_bootstrap': {}}, profile='')
    assert game.start(ctx=ctx) is BootstrapResult.SKIPPED


def case_unknown_profile():
    _current['adapter'] = None
    ctx = FakeCtx({'game_profile': 'nope', 'game_bootstrap': {}}, profile='nope')
    error = expect_error(BootstrapError, lambda: game.start(ctx=ctx))
    assert 'nope' in str(error)


def case_launch_timeout():
    adapter = FakeAdapter(ready_after=10 ** 6, login_times=0)
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config(boot_timeout=0.15))
    expect_error(BootstrapError, lambda: game.start(ctx=ctx))
    assert 'bootstrap_launch_timeout' in ctx.shots, ctx.shots
    assert adapter.launch_calls == 1


def case_login_timeout():
    adapter = FakeAdapter(ready_after=10 ** 6, login_times=1)
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config(enter_timeout=0.15))
    expect_error(BootstrapError, lambda: game.start(ctx=ctx))
    assert 'bootstrap_login_timeout' in ctx.shots, ctx.shots


def case_tap_login_disabled():
    adapter = FakeAdapter(ready_after=10 ** 6, login_times=1)
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config(boot_timeout=0.15))
    expect_error(BootstrapError, lambda: game.start(ctx=ctx, tap_login=False))
    assert adapter.tap_calls == 0


def case_tap_failed():
    adapter = FakeAdapter(ready_after=10 ** 6, login_times=1, tap_ok=False)
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config())
    error = expect_error(BootstrapError, lambda: game.start(ctx=ctx))
    assert '点击' in str(error)
    assert 'bootstrap_tap_failed' in ctx.shots


def case_stop_uses_adapter():
    adapter = FakeAdapter(stop_hook=lambda ctx: setattr(adapter, 'stop_calls', 1))
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config())
    assert game.stop(ctx=ctx) is True
    assert adapter.stop_calls == 1


def case_stop_force():
    adapter = FakeAdapter()
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config())
    ctx.pidof_output = ''
    assert game.stop(ctx=ctx) is True
    assert any('force-stop' in cmd for cmd in ctx.shells), ctx.shells


def case_stop_still_running():
    adapter = FakeAdapter()
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config())
    ctx.pidof_output = '12345'
    assert game.stop(ctx=ctx) is False


def case_restart_order():
    order = []
    adapter = FakeAdapter(ready_after=0)
    adapter.stop = lambda ctx: order.append('stop')
    adapter.launch = lambda ctx: order.append('launch')
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config())
    game.restart(ctx=ctx)
    assert order == ['stop'], order


def case_status():
    adapter = FakeAdapter(ready_after=0, login_times=0)
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config())
    ctx.pidof_output = '999'
    snapshot = game.status(ctx=ctx)
    assert snapshot.ready is True and snapshot.running is True
    assert snapshot.package == 'com.demo.game'


def case_dismiss_throttled():
    adapter = FakeAdapter(ready_after=2, login_times=0)
    _current['adapter'] = adapter
    ctx = FakeCtx(make_config(boot_timeout=0.3, dismiss_interval=0.0, max_dismiss=3,
                              confirm_hits=2))
    ctx.dismiss_result = True
    game.start(ctx=ctx)
    assert 1 <= ctx.dismiss_calls <= 3, ctx.dismiss_calls


def case_session_batch():
    session = BootstrapSession()
    assert session.should_check() is True          # 批外：每次检查
    session.mark_checked()
    assert session.should_check() is True

    session.begin_batch()
    assert session.should_check() is True          # 批内第一次
    session.mark_checked()
    assert session.should_check() is False         # 批内第二次起跳过

    session.invalidate()
    assert session.should_check() is True          # 失败后重查一次
    session.end_batch()
    assert session.should_check() is True


CASES = [
    ('start.already_ready', case_already_ready),
    ('start.tap_login', case_tap_login),
    ('start.launch_then_tap', case_launch_then_tap),
    ('start.no_profile', case_no_profile),
    ('start.unknown_profile', case_unknown_profile),
    ('start.launch_timeout', case_launch_timeout),
    ('start.login_timeout', case_login_timeout),
    ('start.tap_login_disabled', case_tap_login_disabled),
    ('start.tap_failed', case_tap_failed),
    ('stop.adapter_hook', case_stop_uses_adapter),
    ('stop.force_stop', case_stop_force),
    ('stop.still_running', case_stop_still_running),
    ('restart.order', case_restart_order),
    ('status.snapshot', case_status),
    ('start.dismiss_throttled', case_dismiss_throttled),
    ('session.batch', case_session_batch),
]


def main():
    game.create = fake_create
    for name, func in CASES:
        run(name, func)
    print(f'{len(CASES)}/{len(CASES)} passed')


if __name__ == '__main__':
    main()
