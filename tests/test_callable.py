"""任务调用任务的离线测试。

运行：``python tests/test_callable.py``
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime import helpers  # noqa: E402
from src.runtime.callable import (  # noqa: E402
    MAX_CALL_DEPTH,
    CallableTask,
    TaskCallError,
    callable_task,
)
from src.tasks.MyBaseTask import MyBaseTask  # noqa: E402

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


def expect_error(exc_type, func, contains=''):
    try:
        func()
    except exc_type as exc:
        assert contains in str(exc), f'异常消息缺少 {contains!r}: {exc}'
        return
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f'期望 {exc_type.__name__}，实际 {type(exc).__name__}: {exc}') from exc
    raise AssertionError(f'期望 {exc_type.__name__}，但没有抛错')


class FakeExecutor:
    def __init__(self, config=None):
        self.config = config if config is not None else {'helper_tasks': []}
        self.scene = None


class Base(MyBaseTask):
    """记录型任务基类：屏蔽真实设备调用。"""

    SKIP_GAME_BOOTSTRAP = True

    def __init__(self, *args, **kwargs):
        self.events = []
        self.shots = []
        super().__init__(*args, **kwargs)

    def log_info(self, message):
        self.events.append(('info', message))

    def log_warning(self, message):
        self.events.append(('warn', message))

    def screenshot(self, name=None, *args, **kwargs):
        self.shots.append(name)

    def ensure_game_ready(self):
        self.events.append(('bootstrap',))
        return None


class Double(CallableTask):
    """把参数翻倍。"""

    def execute(self, value):
        return value * 2


class Boom(CallableTask):
    """总是抛错。"""

    def execute(self):
        raise ValueError('内层炸了')


class Outer(Base):
    pass


def make(cls=Outer, config=None):
    return cls(executor=FakeExecutor(config), app=None)


def test_returns_execute_result():
    task = make()
    assert task.call_task(Double, value=3) == 6


def test_call_by_registered_name():
    helpers.reset()
    helpers.register('Double', Double)
    task = make()
    assert task.call_task('Double', value=5) == 10


def test_missing_param_reports_name():
    task = make()
    expect_error(TaskCallError, lambda: task.call_task(Boom), 'Boom')
    expect_error(TaskCallError, lambda: task.call_task(Double), '缺少参数')


def test_unknown_param_rejected():
    task = make()
    expect_error(TaskCallError, lambda: task.call_task(Double, nope=1), '不接受参数')
    expect_error(TaskCallError, lambda: task.call_task('Missing'), '未注册')


def test_inner_error_is_wrapped():
    task = make()
    expect_error(TaskCallError, lambda: task.call_task(Boom), 'Outer -> Boom')
    assert task.shots == ['call_failed_Boom'], task.shots


def test_depth_guard():
    task = make()
    task._call_depth = MAX_CALL_DEPTH
    expect_error(TaskCallError, lambda: task.call_task(Double, value=1), '层数')


def test_decorator_builds_task():
    @callable_task
    def add_one(task, value=0):
        return value + 1

    task = make()
    assert task.call_task(add_one, value=41) == 42
    assert add_one.__name__ == 'AddOneTask'


def test_plain_task_rejects_params():
    class Plain(Base):
        def run(self):
            return 'ok'

    task = make()
    expect_error(TaskCallError, lambda: task.call_task(Plain, value=1), 'CallableTask')


def main() -> int:
    for name, func in [
        ('callable.result', test_returns_execute_result),
        ('callable.by_name', test_call_by_registered_name),
        ('callable.missing_param', test_missing_param_reports_name),
        ('callable.unknown_param', test_unknown_param_rejected),
        ('callable.inner_error', test_inner_error_is_wrapped),
        ('callable.depth_guard', test_depth_guard),
        ('callable.decorator', test_decorator_builds_task),
        ('callable.plain_task', test_plain_task_rejects_params),
    ]:
        check(name, func)

    failed = [item for item in results if not item[1]]
    for name, ok, message in results:
        print(f'{"PASS" if ok else "FAIL"} {name}' + (f': {message}' if message else ''))
    print(f'\n{len(results) - len(failed)}/{len(results)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
