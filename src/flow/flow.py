"""线性驱动器：按顺序执行一组 ``Step``。"""

import inspect
import time
from typing import Any, Iterable, Optional, Sequence

from src.flow.steps import FlowConfigError, FlowFailed, Step

DEFAULT_WAIT_TIMEOUT = 8.0


def run_step(task: Any, step: Step, *, wait_timeout: float = DEFAULT_WAIT_TIMEOUT) -> None:
    """执行单个步骤，内部处理重试与失败取证。

    Args:
      task: 任务实例，需要提供导航、点击、等待、日志与截图能力。
      step: 要执行的步骤。
      wait_timeout: 等待 ``step.wait`` 模板的上限（秒）。

    Raises:
      FlowFailed: 重试用尽且不允许跳过时抛出。
    """
    last_error: Optional[BaseException] = None
    for attempt in range(1, step.attempts + 1):
        started = time.monotonic()
        try:
            _ensure_page(task, step)
            _run_action(task, step)
            _wait_after(task, step, wait_timeout)
            _check_expect(task, step)
        except Exception as error:  # noqa: BLE001 - 任何异常都算这一步失败
            last_error = error
            if attempt < step.attempts:
                task.log_warning(f'flow: {step.describe()} 第 {attempt} 次失败，重试: {error}')
                continue
            break
        task.report_progress()
        elapsed = (time.monotonic() - started) * 1000
        task.log_info(f'flow: {step.name} ({elapsed:.0f}ms)')
        return

    if step.optional or step.on_fail == 'skip':
        task.log_warning(f'flow: 跳过 {step.describe()}: {last_error}')
        return

    name = getattr(task, 'name', None) or type(task).__name__
    task.screenshot(f'flow_fail_{name}_{step.name}')
    raise FlowFailed(f'{step.describe()} 执行失败: {last_error}') from last_error


def _ensure_page(task: Any, step: Step) -> None:
    if step.goto:
        task.ensure_page(step.goto)


def _run_action(task: Any, step: Step) -> None:
    """执行步骤动作，并把 ``call`` 的返回值写入任务数据。"""
    if step.call is not None:
        task.data[step.name] = _call(step.call, task)
        return
    if step.action is not None:
        step.action.run(task)


def _call(func: Any, task: Any) -> Any:
    """调用自定义函数：无参时直接调，有参时传入任务。"""
    try:
        params = [param for param in inspect.signature(func).parameters.values()
                  if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)]
    except (TypeError, ValueError):
        return func(task)
    return func() if not params else func(task)


def _wait_after(task: Any, step: Step, timeout: float) -> None:
    if step.wait and not task.wait_template(step.wait, timeout):
        raise FlowFailed(f'等待模板超时: {step.wait}')


def _check_expect(task: Any, step: Step) -> None:
    if step.expect is not None and not step.expect(task):
        raise FlowFailed('expect 断言失败')


class Flow:
    """顺序执行的步骤列表。

    Attributes:
      steps: 不可变的步骤序列。
    """

    def __init__(self, steps: Iterable[Step]):
        self.steps: Sequence[Step] = tuple(steps)
        for step in self.steps:
            if not isinstance(step, Step):
                raise FlowConfigError(f'Flow 只接受 Step，收到 {type(step).__name__}')

    def run(self, task: Any) -> None:
        """依次执行所有步骤。

        Args:
          task: 任务实例。
        """
        for step in self.steps:
            run_step(task, step)

    def describe(self) -> str:
        """返回步骤名列表，便于日志与测试断言。"""
        return ' -> '.join(step.name for step in self.steps)
