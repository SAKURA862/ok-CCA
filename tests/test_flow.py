"""编排层（P3.5）离线测试：``Step``/``Flow``/``StateMachine``、动作与任务接入。

运行：``python tests/test_flow.py``
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.flow import (  # noqa: E402
    Flow,
    FlowConfigError,
    FlowFailed,
    State,
    StateMachine,
    Step,
)
from src.flow.actions import (  # noqa: E402
    Drag,
    KeyCombo,
    KeyPress,
    LongPress,
    RightTap,
    Swipe,
    Tap,
    TextInput,
)
from src.tasks.MyBaseTask import MyBaseTask  # noqa: E402

BOX = (100, 200, 40, 20)
CENTER = (120, 210)

results: list[tuple[str, bool, str]] = []


def check(name, func):
    try:
        func()
    except AssertionError as exc:
        results.append((name, False, str(exc)))
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, f'{type(exc).__name__}: {exc}'))
    else:
        results.append((name, True, ''))


def expect_error(exc_type, func):
    try:
        func()
    except exc_type:
        return
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f'期望 {exc_type.__name__}，实际 {type(exc).__name__}: {exc}') from exc
    raise AssertionError(f'期望 {exc_type.__name__}，但没有抛错')


class FakeBox:
    """模板匹配结果的最小替身。"""

    def __init__(self, x, y, width, height):
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class FakeBehaviour:
    """测试替身：记录每次输入，并按预设制造匹配失败。"""

    name = 'FakeTask'
    width = 1920
    height = 1080

    def setup(self):
        self.data = {}
        self.events = []
        self.shots = []
        self.infos = []
        self.warnings = []
        self.progress = 0
        self.missing = {}
        self.wait_results = {}

    def ensure_page(self, page):
        self.events.append(('ensure', page))

    def find_one(self, name, box=None, threshold=0):
        self.events.append(('find', name))
        left = self.missing.get(name, 0)
        if left > 0:
            self.missing[name] = left - 1
            return None
        return FakeBox(*BOX)

    def click(self, x, y, key='left'):
        self.events.append(('click', x, y, key))

    def swipe(self, from_x, from_y, to_x, to_y, duration=0.5, settle_time=0):
        self.events.append(('swipe', (from_x, from_y), (to_x, to_y), duration))

    def adb_shell(self, *args):
        self.events.append(('adb',) + tuple(args))

    def mouse_down(self, x, y, key='left'):
        self.events.append(('down', x, y))

    def mouse_up(self, key='left'):
        self.events.append(('up',))

    def send_key(self, key, down_time=0.02):
        self.events.append(('key', key, down_time))

    def send_key_down(self, key):
        self.events.append(('key_down', key))

    def send_key_up(self, key):
        self.events.append(('key_up', key))

    def input_text(self, text):
        self.events.append(('text', text))

    def sleep(self, seconds):
        self.events.append(('sleep', round(float(seconds), 3)))

    def wait_template(self, template, timeout=0):
        self.events.append(('wait', template))
        return self._take(self.wait_results, template)

    def screenshot(self, name):
        self.shots.append(name)

    def log_info(self, message):
        self.infos.append(message)

    def log_warning(self, message):
        self.warnings.append(message)

    def report_progress(self):
        self.progress += 1

    def input_events(self):
        """只取输入相关事件，过滤 find/wait/sleep。"""
        return [event for event in self.events if event[0] in
                ('click', 'swipe', 'adb', 'down', 'up', 'key', 'key_down', 'key_up', 'text')]

    @staticmethod
    def _take(queue_map, key):
        queue = queue_map.get(key)
        if isinstance(queue, list):
            return queue.pop(0) if queue else True
        return True if queue is None else bool(queue)


class FakeTask(FakeBehaviour):
    def __init__(self):
        self.setup()

    def bound_value(self):
        return 7


# ---------------------------------------------------------------- Step / Flow


def test_step_validation():
    expect_error(FlowConfigError, lambda: Step('', call=lambda t: None))
    expect_error(FlowConfigError, lambda: Step('x'))
    expect_error(FlowConfigError, lambda: Step('x', click='a', key='b'))
    expect_error(FlowConfigError, lambda: Step('x', click='a', on_fail='ignore'))
    expect_error(FlowConfigError, lambda: Step('x', click='a', retry=-1))
    assert Step('x', click='a').attempts == 2
    assert Step('x', click='a', retry=3).attempts == 4


def test_flow_runs_in_order():
    task = FakeTask()
    flow = Flow([Step('a', click='btn_a'),
                 Step('b', key='escape'),
                 Step('c', click_point=(0.5, 0.6))])
    flow.run(task)
    assert task.input_events() == [('click', *CENTER, 'left'),
                                   ('key', 'escape', 0.02),
                                   ('click', 960, 648, 'left')], task.input_events()
    assert task.progress == 3


def test_flow_goto_before_action():
    task = FakeTask()
    Flow([Step('open', goto='home', click='btn')]).run(task)
    assert task.events[0] == ('ensure', 'home'), task.events
    assert ('find', 'btn') in task.events


def test_goto_only_step():
    task = FakeTask()
    Flow([Step('navigate', goto='home')]).run(task)
    assert task.events == [('ensure', 'home')], task.events


def test_retry_then_success():
    task = FakeTask()
    task.missing['btn'] = 1
    Flow([Step('click', click='btn', retry=1)]).run(task)
    assert len([event for event in task.events if event == ('find', 'btn')]) == 2, task.events
    assert len([event for event in task.input_events() if event[0] == 'click']) == 1
    assert task.warnings and '重试' in task.warnings[0], task.warnings


def test_retry_exhausted_aborts_with_evidence():
    task = FakeTask()
    task.missing['btn'] = 5
    expect_error(FlowFailed, lambda: Flow([Step('open', click='btn', retry=1)]).run(task))
    assert task.shots == ['flow_fail_FakeTask_open'], task.shots


def test_on_fail_skip():
    task = FakeTask()
    task.missing['missing'] = 5
    flow = Flow([Step('bad', click='missing', retry=0, on_fail='skip'),
                 Step('good', click='ok')])
    flow.run(task)
    assert [event for event in task.input_events() if event[0] == 'click'] == [
        ('click', *CENTER, 'left')], task.input_events()
    assert not task.shots


def test_optional_wait_timeout_is_not_failure():
    task = FakeTask()
    task.wait_results['popup'] = [False]
    Flow([Step('maybe', click='btn', wait='popup', optional=True)]).run(task)
    assert task.warnings, '应记录一条跳过警告'
    assert not task.shots


def test_expect_false_fails():
    task = FakeTask()
    flow = Flow([Step('check', call=lambda t: 1, expect=lambda t: False, retry=0)])
    expect_error(FlowFailed, lambda: flow.run(task))
    assert task.shots == ['flow_fail_FakeTask_check'], task.shots


def test_click_point_callable():
    task = FakeTask()
    Flow([Step('p', click_point=lambda t: (0.25, 0.75))]).run(task)
    assert task.input_events() == [('click', 480, 810, 'left')], task.input_events()


def test_call_result_stored():
    task = FakeTask()
    Flow([Step('read', call=lambda t: 42)]).run(task)
    assert task.data == {'read': 42}, task.data


def test_call_bound_method():
    task = FakeTask()
    Flow([Step('read', call=task.bound_value)]).run(task)
    assert task.data == {'read': 7}, task.data


# -------------------------------------------------------------------- 动作层


def test_action_tap_template():
    task = FakeTask()
    Flow([Step('t', action=Tap(template='btn'))]).run(task)
    assert task.input_events() == [('click', *CENTER, 'left')], task.input_events()


def test_action_sugar_matches_object():
    sugar = FakeTask()
    explicit = FakeTask()
    Flow([Step('t', click='btn')]).run(sugar)
    Flow([Step('t', action=Tap(template='btn'))]).run(explicit)
    assert sugar.input_events() == explicit.input_events(), (sugar.input_events(), explicit.input_events())


def test_action_right_tap_and_double_tap():
    task = FakeTask()
    Flow([Step('r', action=RightTap(template='btn')),
          Step('d', action=Tap(point=(0.1, 0.1)))]).run(task)
    assert task.input_events() == [('click', *CENTER, 'right'),
                                   ('click', 192, 108, 'left')], task.input_events()


def test_action_long_press_uses_motionevent():
    task = FakeTask()
    Flow([Step('l', action=LongPress(template='btn', hold=0.5))]).run(task)
    assert task.input_events() == [
        ('adb', 'input', 'motionevent', 'DOWN', *CENTER),
        ('adb', 'input', 'motionevent', 'UP', *CENTER),
    ], task.input_events()
    assert ('sleep', 0.5) in task.events


def test_action_swipe():
    task = FakeTask()
    Flow([Step('s', action=Swipe(start=(0.8, 0.7), end=(0.8, 0.3), duration=0.4))]).run(task)
    assert task.input_events() == [('swipe', (1536, 756), (1536, 324), 0.4)], task.input_events()


def test_action_drag_holds_before_release():
    task = FakeTask()
    Flow([Step('g', action=Drag(start=(0.5, 0.8), end=(0.5, 0.3), duration=0.6, hold=0.2))]).run(task)
    events = task.input_events()
    assert events[0] == ('adb', 'input', 'motionevent', 'DOWN', 960, 864), events[0]
    assert events[-1] == ('adb', 'input', 'motionevent', 'UP', 960, 324), events[-1]
    moves = [event for event in events if event[3] == 'MOVE']
    assert len(moves) == 6, moves
    assert moves[0][-2:] == (960, 774), moves[0]
    sleep_after_last_move = task.events[task.events.index(events[-2]) + 1]
    assert sleep_after_last_move == ('sleep', 0.2), sleep_after_last_move


def test_action_key_hold_and_combo():
    task = FakeTask()
    Flow([Step('h', action=KeyPress('enter', hold=1.0)),
          Step('c', action=KeyCombo(('ctrl', 'a')))]).run(task)
    assert task.input_events() == [
        ('key_down', 'enter'), ('key_up', 'enter'),
        ('key_down', 'ctrl'), ('key_down', 'a'), ('key_up', 'a'), ('key_up', 'ctrl'),
    ], task.input_events()
    assert ('sleep', 1.0) in task.events


def test_action_text_input_with_target():
    task = FakeTask()
    Flow([Step('t', action=TextInput('hello world', template='search'))]).run(task)
    assert task.input_events() == [('click', *CENTER, 'left'), ('text', 'hello%sworld')], \
        task.input_events()
    assert ('sleep', 0.4) in task.events


def test_action_text_input_without_target():
    task = FakeTask()
    Flow([Step('t', action=TextInput('abc'))]).run(task)
    assert task.input_events() == [('text', 'abc')], task.input_events()


def test_action_validation():
    expect_error(FlowConfigError, lambda: Tap())
    expect_error(FlowConfigError, lambda: Tap(template='x', point=(0.1, 0.1)))
    expect_error(FlowConfigError, lambda: Tap(point=(0.1, 0.1), relative=(0.9, 0.9)))
    expect_error(FlowConfigError, lambda: Step('x', action=Tap('a'), click='b'))
    expect_error(FlowConfigError, lambda: Step('x', action=Tap('a'), call=lambda t: 1))
    expect_error(FlowConfigError, lambda: TextInput('中文'))
    expect_error(FlowConfigError, lambda: KeyCombo(('ctrl',)))


# ---------------------------------------------------------------- 状态机与任务


def test_state_machine_branching():
    task = FakeTask()

    def bump(t):
        t.data['n'] = t.data.get('n', 0) + 1

    machine = StateMachine({
        'a': State('a', do=bump, transitions=[(lambda t: t.data['n'] < 3, 'b')]),
        'b': State('b', do=bump, transitions=[(lambda t: t.data['n'] < 3, 'a')]),
    })
    final = machine.run(task)
    assert task.data['n'] == 3, task.data
    assert final == 'a', final


def test_state_machine_max_transitions():
    task = FakeTask()
    machine = StateMachine({'loop': State('loop', transitions=[(lambda t: True, 'loop')])},
                           max_transitions=3)
    expect_error(FlowFailed, lambda: machine.run(task))


def test_state_machine_step_list():
    task = FakeTask()
    machine = StateMachine({
        'only': State('only', goto='home', do=[Step('a', click='x'), Step('b', key='esc')]),
    })
    machine.run(task)
    assert task.events[0] == ('ensure', 'home'), task.events
    assert task.input_events() == [('click', *CENTER, 'left'), ('key', 'esc', 0.02)], \
        task.input_events()


class ProbeTask(FakeBehaviour, MyBaseTask):
    """只实现 build_flow 的任务，验证默认 run。"""

    SKIP_GAME_BOOTSTRAP = True

    def build_flow(self):
        return Flow([Step('go', call=lambda t: 'done')])


def test_build_flow_task_end_to_end():
    task = object.__new__(ProbeTask)
    task.setup()
    task._bootstrap_done = False
    task.run()
    assert task.data == {'go': 'done'}, task.data
    assert task.progress == 1


class EmptyTask(FakeBehaviour, MyBaseTask):
    SKIP_GAME_BOOTSTRAP = True


def test_missing_flow_raises():
    task = object.__new__(EmptyTask)
    task.setup()
    task._bootstrap_done = False
    expect_error(Exception, task.run)


def main() -> int:
    for name, func in [
        ('step.validation', test_step_validation),
        ('flow.order', test_flow_runs_in_order),
        ('flow.goto', test_flow_goto_before_action),
        ('flow.goto_only', test_goto_only_step),
        ('flow.retry_then_success', test_retry_then_success),
        ('flow.retry_exhausted', test_retry_exhausted_aborts_with_evidence),
        ('flow.on_fail_skip', test_on_fail_skip),
        ('flow.optional', test_optional_wait_timeout_is_not_failure),
        ('flow.expect_false', test_expect_false_fails),
        ('flow.click_point', test_click_point_callable),
        ('flow.call_result', test_call_result_stored),
        ('flow.call_bound_method', test_call_bound_method),
        ('action.tap_template', test_action_tap_template),
        ('action.sugar_matches_object', test_action_sugar_matches_object),
        ('action.right_and_point', test_action_right_tap_and_double_tap),
        ('action.long_press', test_action_long_press_uses_motionevent),
        ('action.swipe', test_action_swipe),
        ('action.drag', test_action_drag_holds_before_release),
        ('action.key_hold_and_combo', test_action_key_hold_and_combo),
        ('action.text_with_target', test_action_text_input_with_target),
        ('action.text_without_target', test_action_text_input_without_target),
        ('action.validation', test_action_validation),
        ('state.branching', test_state_machine_branching),
        ('state.max_transitions', test_state_machine_max_transitions),
        ('state.step_list', test_state_machine_step_list),
        ('task.build_flow_end_to_end', test_build_flow_task_end_to_end),
        ('task.missing_flow', test_missing_flow_raises),
    ]:
        check(name, func)

    failed = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f'  -> {detail}' if detail else ''))
        failed += 0 if ok else 1
    print(f'\n{len(results) - failed}/{len(results)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
