"""编排层离线测试：步骤、动作、驱动器与任务接入。

运行：``python tests/test_flow.py``
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.flow import (  # noqa: E402
    Click,
    DoubleClick,
    Drag,
    Flow,
    FlowAborted,
    FlowConfigError,
    FlowFailed,
    KeyCombo,
    KeyPress,
    LongPress,
    Loop,
    RightClick,
    State,
    StateMachine,
    Step,
    Stop,
    Swipe,
    InputText,
)
from src.flow.actions import Tap  # noqa: E402  旧名别名
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

    def move(self, x, y):
        self.events.append(('move', x, y))

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
                ('click', 'swipe', 'adb', 'down', 'move', 'up', 'key', 'key_down', 'key_up', 'text')]

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
    expect_error(FlowConfigError, lambda: Step('x', click='a', key_press='b'))
    expect_error(FlowConfigError, lambda: Step('x', click='a', on_fail='ignore'))
    expect_error(FlowConfigError, lambda: Step('x', click='a', retry=-1))
    assert Step('x', click='a').attempts == 2
    assert Step('x', click='a', retry=3).attempts == 4


def test_legacy_fields_report_migration():
    expect_error(FlowConfigError, lambda: Step('x', click_point=(0.5, 0.5)))
    expect_error(FlowConfigError, lambda: Step('x', key='esc'))


def test_sugar_names_match_actions():
    assert isinstance(Step('a', click='x').action, Click)
    assert isinstance(Step('a', double_click='x').action, DoubleClick)
    assert isinstance(Step('a', right_click='x').action, RightClick)
    assert isinstance(Step('a', long_press='x').action, LongPress)
    assert isinstance(Step('a', key_press='esc').action, KeyPress)
    assert Tap is Click


def test_flow_runs_in_order():
    task = FakeTask()
    flow = Flow([Step('a', click='btn_a'),
                 Step('b', key_press='escape'),
                 Step('c', click=(0.5, 0.6))])
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


def test_when_skips_step():
    task = FakeTask()
    Flow([Step('skip_me', click='btn', when=lambda t: False),
          Step('run_me', click='ok')]).run(task)
    assert [event for event in task.input_events() if event[0] == 'click'] == [
        ('click', *CENTER, 'left')], task.input_events()
    assert any('skip (when)' in message for message in task.infos), task.infos


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


def test_call_result_stored():
    task = FakeTask()
    Flow([Step('read', call=lambda t: 42)]).run(task)
    assert task.data == {'read': 42}, task.data


def test_call_bound_method():
    task = FakeTask()
    Flow([Step('read', call=task.bound_value)]).run(task)
    assert task.data == {'read': 7}, task.data


def test_flow_final_runs_on_success():
    task = FakeTask()
    Flow([Step('a', click='x')], final=[Step('wrap', click='y')]).run(task)
    assert [event for event in task.input_events() if event[0] == 'click'] == [
        ('click', *CENTER, 'left'), ('click', *CENTER, 'left')], task.input_events()


def test_flow_final_runs_on_failure():
    task = FakeTask()
    task.missing['boom'] = 5
    flow = Flow([Step('a', click='boom', retry=0)], final=[Step('wrap', click='y')])
    expect_error(FlowFailed, lambda: flow.run(task))
    assert task.data.get('error'), task.data
    assert len([event for event in task.input_events() if event[0] == 'click']) == 1


def test_stop_aborts_and_keeps_final():
    task = FakeTask()
    flow = Flow([Step('a', click='x'), Stop('够了'), Step('never', click='z')],
                final=[Step('wrap', click='y')])
    expect_error(FlowAborted, lambda: flow.run(task))
    assert task.shots == [], task.shots
    assert len([event for event in task.input_events() if event[0] == 'click']) == 2


def test_duplicate_step_names_rejected():
    expect_error(FlowConfigError, lambda: Flow([Step('a', click='x'), Step('a', click='y')]))


def test_flow_rejects_unknown_node():
    expect_error(FlowConfigError, lambda: Flow([Step('a', click='x'), 'not-a-step']))


# -------------------------------------------------------------------- 动作层


def test_action_click_template():
    task = FakeTask()
    Flow([Step('t', action=Click(template='btn'))]).run(task)
    assert task.input_events() == [('click', *CENTER, 'left')], task.input_events()


def test_action_sugar_matches_object():
    sugar = FakeTask()
    explicit = FakeTask()
    Flow([Step('t', click='btn')]).run(sugar)
    Flow([Step('t', action=Click(template='btn'))]).run(explicit)
    assert sugar.input_events() == explicit.input_events(), (
        sugar.input_events(), explicit.input_events())


def test_action_right_click_and_double_click():
    task = FakeTask()
    Flow([Step('r', action=RightClick(template='btn')),
          Step('d', action=DoubleClick(point=(0.1, 0.1)))]).run(task)
    clicks = [event for event in task.input_events() if event[0] == 'click']
    assert clicks[0] == ('click', *CENTER, 'right'), clicks
    assert clicks[1:] == [('click', 192, 108, 'left'), ('click', 192, 108, 'left')], clicks


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
    Flow([Step('s', action=Swipe(start=(0.8, 0.7), end=(0.8, 0.3),
                                 duration=0.4))]).run(task)
    assert task.input_events() == [('swipe', (1536, 756), (1536, 324), 0.4)], task.input_events()


def test_action_drag_uses_motionevent():
    task = FakeTask()
    Flow([Step('g', action=Drag(start=(0.5, 0.8), end=(0.5, 0.3),
                                duration=0.6, hold=0.2))]).run(task)
    events = task.input_events()
    assert events[0] == ('adb', 'input', 'motionevent', 'DOWN', 960, 864), events[0]
    assert events[-1] == ('adb', 'input', 'motionevent', 'UP', 960, 324), events[-1]
    moves = [event for event in events if event[3] == 'MOVE']
    assert len(moves) == 6, moves
    assert moves[0][-2:] == (960, 774), moves[0]


def test_action_drag_falls_back_to_mouse():
    task = FakeTask()
    task.adb_shell = None  # 模拟 Windows 后端：没有 adb
    Flow([Step('g', action=Drag(start=(0.5, 0.8), end=(0.5, 0.3),
                                hold=0.2))]).run(task)
    events = task.input_events()
    assert events[0] == ('down', 960, 864), events
    assert [event for event in events if event[0] == 'move'], events
    assert events[-1] == ('up',), events


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
    Flow([Step('t', action=InputText('hello world', template='search'))]).run(task)
    assert task.input_events() == [('click', *CENTER, 'left'), ('text', 'hello%sworld')], \
        task.input_events()
    assert ('sleep', 0.4) in task.events


def test_action_text_input_without_target():
    task = FakeTask()
    Flow([Step('t', action=InputText('abc'))]).run(task)
    assert task.input_events() == [('text', 'abc')], task.input_events()


def test_action_validation():
    expect_error(FlowConfigError, lambda: Click())
    expect_error(FlowConfigError, lambda: Click(template='x', point=(0.1, 0.1)))
    expect_error(FlowConfigError, lambda: Click(point=(0.1, 0.1), relative=(0.9, 0.9)))
    expect_error(FlowConfigError, lambda: Step('x', action=Click('a'), click='b'))
    expect_error(FlowConfigError, lambda: Step('x', action=Click('a'), call=lambda t: 1))
    expect_error(FlowConfigError, lambda: InputText('中文'))
    expect_error(FlowConfigError, lambda: KeyCombo(('ctrl',)))


# ---------------------------------------------------------------- 状态机与循环


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


def test_state_machine_step_list_and_flow():
    task = FakeTask()
    machine = StateMachine({
        'only': State('only', goto='home', do=[
            Step('a', click='x'),
            Flow([Step('b', key_press='esc')]),
        ]),
    })
    machine.run(task)
    assert task.events[0] == ('ensure', 'home'), task.events
    assert task.input_events() == [('click', *CENTER, 'left'), ('key', 'esc', 0.02)], \
        task.input_events()


def test_state_machine_final_and_key_mismatch():
    task = FakeTask()
    machine = StateMachine({'a': State('a', do=lambda t: None)},
                           final=[Step('wrap', click='y')])
    machine.run(task)
    assert [event for event in task.input_events() if event[0] == 'click'] == [
        ('click', *CENTER, 'left')], task.input_events()
    expect_error(FlowConfigError, lambda: StateMachine({'a': State('b')}))


def test_loop_until_condition():
    task = FakeTask()

    def bump(t):
        t.data['n'] = t.data.get('n', 0) + 1

    rounds = Loop([Step('tick', call=bump)], until=lambda t: t.data['n'] >= 3,
                  times=10).run(task)
    assert rounds == 3, rounds
    assert task.data['n'] == 3, task.data


def test_loop_exhausted():
    task = FakeTask()
    expect_error(FlowFailed, lambda: Loop([Step('tick', call=lambda t: None)],
                                          until=lambda t: False, times=2).run(task))
    task2 = FakeTask()
    rounds = Loop([Step('tick', call=lambda t: None)], until=lambda t: False,
                  times=2, on_exhausted='warn').run(task2)
    assert rounds == 2, rounds
    assert task2.warnings, task2.warnings


def test_loop_stop_and_final():
    task = FakeTask()
    flow = Loop([Step('a', click='x'), Stop('done')], times=5,
                final=[Step('wrap', click='y')])
    expect_error(FlowAborted, lambda: flow.run(task))
    assert len([event for event in task.input_events() if event[0] == 'click']) == 2


# ----------------------------------------------------------------------- 任务


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


def test_stop_if_helper():
    task = object.__new__(ProbeTask)
    task.setup()
    flow = Flow([Step('check', call=lambda t: t.stop_if(True, '够了'))])
    expect_error(FlowAborted, lambda: flow.run(task))


def main() -> int:
    for name, func in [
        ('step.validation', test_step_validation),
        ('step.legacy_fields', test_legacy_fields_report_migration),
        ('step.sugar_names', test_sugar_names_match_actions),
        ('flow.order', test_flow_runs_in_order),
        ('flow.goto', test_flow_goto_before_action),
        ('flow.goto_only', test_goto_only_step),
        ('flow.when', test_when_skips_step),
        ('flow.retry_then_success', test_retry_then_success),
        ('flow.retry_exhausted', test_retry_exhausted_aborts_with_evidence),
        ('flow.on_fail_skip', test_on_fail_skip),
        ('flow.optional', test_optional_wait_timeout_is_not_failure),
        ('flow.expect_false', test_expect_false_fails),
        ('flow.call_result', test_call_result_stored),
        ('flow.call_bound_method', test_call_bound_method),
        ('flow.final_ok', test_flow_final_runs_on_success),
        ('flow.final_error', test_flow_final_runs_on_failure),
        ('flow.stop', test_stop_aborts_and_keeps_final),
        ('flow.duplicate_names', test_duplicate_step_names_rejected),
        ('flow.unknown_node', test_flow_rejects_unknown_node),
        ('action.click_template', test_action_click_template),
        ('action.sugar_matches_object', test_action_sugar_matches_object),
        ('action.right_and_double', test_action_right_click_and_double_click),
        ('action.long_press', test_action_long_press_uses_motionevent),
        ('action.swipe', test_action_swipe),
        ('action.drag_motionevent', test_action_drag_uses_motionevent),
        ('action.drag_mouse', test_action_drag_falls_back_to_mouse),
        ('action.key_hold_and_combo', test_action_key_hold_and_combo),
        ('action.text_with_target', test_action_text_input_with_target),
        ('action.text_without_target', test_action_text_input_without_target),
        ('action.validation', test_action_validation),
        ('state.branching', test_state_machine_branching),
        ('state.max_transitions', test_state_machine_max_transitions),
        ('state.step_list', test_state_machine_step_list_and_flow),
        ('state.final', test_state_machine_final_and_key_mismatch),
        ('loop.until', test_loop_until_condition),
        ('loop.exhausted', test_loop_exhausted),
        ('loop.stop', test_loop_stop_and_final),
        ('task.build_flow_end_to_end', test_build_flow_task_end_to_end),
        ('task.missing_flow', test_missing_flow_raises),
        ('task.stop_if', test_stop_if_helper),
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
