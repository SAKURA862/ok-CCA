"""弹窗层与跨日判定的状态机测试（不依赖设备、不依赖 GUI）。

运行：``python tests/test_overlay_guard.py``
"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 临时目录统一放仓库 .tmp 下：harness 的 TMP 可能指向仓库根目录，直接 mkdtemp 会污染工作区
TMP_ROOT = ROOT / '.tmp'
TMP_ROOT.mkdir(parents=True, exist_ok=True)


def temp_dir() -> str:
    return tempfile.mkdtemp(dir=TMP_ROOT)

from src.runtime import daily, overlay  # noqa: E402
from src.tasks.MyBaseTask import MyBaseTask  # noqa: E402


class FakeBox:
    def __init__(self, x=10, y=20, width=100, height=40):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    def center(self):
        return self.x + self.width // 2, self.y + self.height // 2


class FakeExecutor:
    def __init__(self, config=None, frame='frame'):
        self.config = config or {}
        self.scene = 'default'
        self.frame = frame

    def next_frame(self):
        return self.frame


class FakeApp:
    pass


class FakeTask:
    """只实现弹窗层用到的四个能力：找图、点击、按键、截图。"""

    def __init__(self, templates=()):
        self.templates = set(templates)
        self.clicks = []
        self.keys = []
        self.shots = []
        self.logs = []

    def find_one(self, template, **kwargs):
        return FakeBox() if template in self.templates else None

    def box_of_screen(self, *args, **kwargs):
        return FakeBox(0, 0, 2560, 1440)

    def click(self, *args, **kwargs):
        self.clicks.append((args, kwargs))

    def send_key(self, key):
        self.keys.append(key)

    def screenshot(self, name=None, **kwargs):
        self.shots.append(name)

    def log_info(self, message, **kwargs):
        self.logs.append(message)


class Clock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_rule(**kwargs):
    base = dict(id='net_retry', template='net_retry', action={'type': 'click_box'})
    base.update(kwargs)
    return overlay.OverlayRule(**base)


results = []


def check(name, func):
    try:
        func()
    except AssertionError as error:
        results.append((name, False, str(error)))
    except Exception as error:  # noqa: BLE001
        results.append((name, False, f'{type(error).__name__}: {error}'))
    else:
        results.append((name, True, ''))


def test_anytime_rule_clicks_matched_box():
    task = FakeTask(templates=['net_retry'])
    clock = Clock()
    guard = overlay.OverlayGuard([make_rule()], clock=clock)
    handled = guard.process(task, 'frame', when='anytime')
    assert handled == 'net_retry', handled
    assert len(task.clicks) == 1, task.clicks
    assert guard.attempts('net_retry') == 1


def test_min_interval_throttles_checks():
    task = FakeTask(templates=['net_retry'])
    clock = Clock()
    guard = overlay.OverlayGuard([make_rule(cooldown=0)], clock=clock, min_interval=0.3)
    assert guard.process(task, 'frame') == 'net_retry'
    clock.advance(0.1)
    assert guard.process(task, 'frame') is None
    clock.advance(0.3)
    assert guard.process(task, 'frame') == 'net_retry'


def test_cooldown_blocks_rapid_refire():
    task = FakeTask(templates=['net_retry'])
    clock = Clock()
    guard = overlay.OverlayGuard([make_rule(cooldown=2.0)], clock=clock, min_interval=0.0)
    assert guard.process(task, 'frame') == 'net_retry'
    clock.advance(1.0)
    assert guard.process(task, 'frame') is None
    clock.advance(1.5)
    assert guard.process(task, 'frame') == 'net_retry'


def test_attempts_reset_after_clean_frame():
    task = FakeTask(templates=['net_retry'])
    clock = Clock()
    guard = overlay.OverlayGuard([make_rule(cooldown=0)], clock=clock, min_interval=0.0)
    guard.process(task, 'frame')
    task.templates.clear()
    assert guard.process(task, 'frame') is None
    assert guard.attempts('net_retry') == 0


def test_max_attempts_raises_stuck_with_screenshot():
    task = FakeTask(templates=['net_retry'])
    clock = Clock()
    guard = overlay.OverlayGuard(
        [make_rule(cooldown=0, max_attempts=3)], clock=clock, min_interval=0.0
    )
    for _ in range(3):
        guard.process(task, 'frame')
    try:
        guard.process(task, 'frame')
    except overlay.OverlayStuck:
        pass
    else:
        raise AssertionError('应当抛出 OverlayStuck')
    assert 'overlay_stuck_net_retry' in task.shots, task.shots
    assert len(task.clicks) == 3, task.clicks


def test_daily_rule_requires_pending():
    task = FakeTask(templates=['daily_signin'])
    clock = Clock()
    rule = make_rule(
        id='daily_signin', template='daily_signin', when=('on_home',), daily=True
    )
    guard = overlay.OverlayGuard([rule], clock=clock, min_interval=0.0)
    assert guard.process(task, 'frame', when='on_home', daily_pending=False) is None
    clock.advance(1)
    assert guard.process(task, 'frame', when='on_home', daily_pending=True) == 'daily_signin'


def test_anytime_rule_not_used_for_home_check():
    task = FakeTask(templates=['net_retry'])
    clock = Clock()
    guard = overlay.OverlayGuard([make_rule()], clock=clock, min_interval=0.0)
    assert guard.process(task, 'frame', when='on_home') is None


def test_disabled_rule_ignored():
    task = FakeTask(templates=['net_retry'])
    guard = overlay.OverlayGuard(
        [make_rule(enabled=False)], clock=Clock(), min_interval=0.0
    )
    assert guard.process(task, 'frame') is None


def test_key_action():
    task = FakeTask(templates=['popup'])
    rule = make_rule(id='popup', template='popup', action={'type': 'key', 'key': 'ESC'})
    guard = overlay.OverlayGuard([rule], clock=Clock(), min_interval=0.0)
    guard.process(task, 'frame')
    assert task.keys == ['ESC'], task.keys


def test_rule_from_dict_and_bad_when():
    rule = overlay.OverlayRule.from_dict({'id': 'x', 'when': ['on_home'], 'template': 't'})
    assert rule.when == ('on_home',)
    try:
        overlay.OverlayRule.from_dict({'id': 'x', 'when': ['nope']})
    except ValueError:
        pass
    else:
        raise AssertionError('未知 when 应当报错')


def test_game_day_boundary():
    assert daily.game_day(datetime(2026, 11, 3, 3, 59)).isoformat() == '2026-11-02'
    assert daily.game_day(datetime(2026, 11, 3, 4, 1)).isoformat() == '2026-11-03'


def test_daily_state_roundtrip():
    with tempfile.TemporaryDirectory() as folder:
        state = daily.DailyState(Path(folder) / 'daily_state.json')
        now = datetime(2026, 11, 3, 10, 0)
        assert state.is_pending(now) is True
        state.mark_done(now)
        assert state.is_pending(now) is False
        # 过了 04:00 才算新的一天
        assert state.is_pending(datetime(2026, 11, 4, 3, 0)) is False
        assert state.is_pending(datetime(2026, 11, 4, 4, 30)) is True


class ProbeTask(MyBaseTask):
    """最小可用的项目任务：不启动游戏，只跑一次 run。"""

    SKIP_GAME_BOOTSTRAP = True

    def run(self):
        self.ran = True


def make_probe_task(config):
    task = ProbeTask(FakeExecutor(config), FakeApp())
    task.clicks = []
    task.click = lambda *args, **kwargs: task.clicks.append((args, kwargs))
    return task


def test_next_frame_runs_anytime_rules():
    folder = temp_dir()
    rules_file = Path(folder) / 'overlays.json'
    rules_file.write_text(
        '[{"id": "net_retry", "template": "net_retry", "action": {"type": "click_box"}}]',
        encoding='utf-8',
    )
    task = make_probe_task({'overlays': {'rules_file': str(rules_file)}})
    task.find_one = lambda template, **kwargs: FakeBox() if template == 'net_retry' else None
    task.next_frame()
    assert len(task.clicks) == 1, task.clicks
    assert task.overlay_guard.handled == ['net_retry']


def test_run_overlays_marks_daily_done_once():
    folder = temp_dir()
    task = make_probe_task({'config_folder': folder})
    task.find_one = lambda template, **kwargs: None
    state = task.daily_state
    assert state.is_pending() is True
    task.run_overlays('on_home')
    assert state.is_pending() is False
    task.run_overlays('on_home')  # 同一天不再重复
    assert state.is_pending() is False


def test_stuck_check_fires_once_per_window():
    task = make_probe_task({'config_folder': temp_dir()})
    task.find_one = lambda template, **kwargs: None
    task._last_progress -= task.STUCK_AFTER + 1
    task._check_stuck('frame')
    first = task._last_stuck_check
    task._check_stuck('frame')
    assert task._last_stuck_check == first, '同一窗口内不应重复触发'


def main():
    check('anytime_rule_clicks', test_anytime_rule_clicks_matched_box)
    check('min_interval', test_min_interval_throttles_checks)
    check('cooldown', test_cooldown_blocks_rapid_refire)
    check('attempts_reset', test_attempts_reset_after_clean_frame)
    check('max_attempts', test_max_attempts_raises_stuck_with_screenshot)
    check('daily_gate', test_daily_rule_requires_pending)
    check('anytime_scope', test_anytime_rule_not_used_for_home_check)
    check('disabled', test_disabled_rule_ignored)
    check('key_action', test_key_action)
    check('from_dict', test_rule_from_dict_and_bad_when)
    check('game_day', test_game_day_boundary)
    check('daily_state', test_daily_state_roundtrip)
    check('next_frame_hook', test_next_frame_runs_anytime_rules)
    check('daily_once', test_run_overlays_marks_daily_done_once)
    check('stuck_window', test_stuck_check_fires_once_per_window)

    failed = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f'  -> {detail}' if detail else ''))
        failed += 0 if ok else 1
    print(f'\n{len(results) - failed}/{len(results)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
