"""线性驱动器：按顺序执行一组 ``Step``。"""

import inspect
import time
from typing import Any, Iterable, Optional, Sequence, Tuple

from src.flow.steps import FlowAborted, FlowConfigError, FlowFailed, Step, Stop

DEFAULT_WAIT_TIMEOUT = 8.0

Node = Any  # Step 或 Stop


def run_steps(task: Any, steps: Iterable[Node], *,
              wait_timeout: float = DEFAULT_WAIT_TIMEOUT) -> None:
    """依次执行一组步骤，遇 ``Stop`` 立即终止。

    Args:
      task: 任务实例。
      steps: 步骤序列。
      wait_timeout: 单步等待模板的上限（秒）。

    Raises:
      FlowAborted: 遇到 ``Stop``。
      FlowFailed: 某步重试用尽。
    """
    for step in steps:
        run_step(task, step, wait_timeout=wait_timeout)


def run_step(task: Any, step: Node, *, wait_timeout: float = DEFAULT_WAIT_TIMEOUT) -> None:
    """执行单个步骤，内部处理守卫、重试与失败取证。

    Args:
      task: 任务实例，需要提供导航、点击、等待、日志与截图能力。
      step: 要执行的步骤或 ``Stop``。
      wait_timeout: 等待 ``step.wait`` 模板的上限（秒）。

    Raises:
      FlowAborted: 步骤是 ``Stop``。
      FlowFailed: 重试用尽且不允许跳过时抛出。
    """
    if isinstance(step, Stop):
        task.log_warning(f'flow: {step.describe()}')
        raise FlowAborted(step.reason)
    if step.when is not None and not _call(step.when, task):
        task.log_info(f'flow: {step.name} skip (when)')
        return

    last_error: Optional[BaseException] = None
    for attempt in range(1, step.attempts + 1):
        started = time.monotonic()
        try:
            _ensure_page(task, step)
            _run_action(task, step)
            _wait_after(task, step, wait_timeout)
            _check_expect(task, step)
        except FlowAborted:
            raise
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


def check_nodes(owner: str, nodes: Iterable[Node]) -> Tuple[Node, ...]:
    """校验容器里的节点类型与步骤名唯一性。

    Args:
      owner: 容器名，用于报错信息。
      nodes: 待校验的节点序列。

    Returns:
      元组形式的节点序列。

    Raises:
      FlowConfigError: 类型不对或步骤名重复。
    """
    result = tuple(nodes)
    seen = set()
    for node in result:
        if not isinstance(node, (Step, Stop)):
            raise FlowConfigError(f'{owner} 只接受 Step 或 Stop，收到 {type(node).__name__}')
        if isinstance(node, Stop):
            continue
        if node.name in seen:
            raise FlowConfigError(f'{owner} 里步骤名重复: {node.name!r}')
        seen.add(node.name)
    return result


def run_final(task: Any, final: Sequence[Node], error: Optional[BaseException],
              *, wait_timeout: float = DEFAULT_WAIT_TIMEOUT) -> None:
    """执行收尾步骤；已有异常时不再抛出新的失败。

    Args:
      task: 任务实例。
      final: 收尾步骤序列。
      error: 主流程抛出的异常，没有则为 None。
      wait_timeout: 等待模板上限。

    Raises:
      BaseException: 主流程没有异常、而收尾步骤失败时抛出。
    """
    if error is not None:
        task.data.setdefault('error', str(error))
    for step in final:
        try:
            run_step(task, step, wait_timeout=wait_timeout)
        except FlowAborted:
            task.log_info('flow: 收尾阶段再次 Stop，忽略')
            return
        except Exception as final_error:  # noqa: BLE001 - 收尾失败不覆盖主异常
            if error is None:
                raise
            task.log_warning(f'flow: 收尾步骤失败，已忽略: {final_error}')
            return


class Flow:
    """顺序执行的步骤列表。

    Attributes:
      steps: 不可变的步骤序列。
      final: 无论成功失败都会执行的收尾步骤。
    """

    def __init__(self, steps: Iterable[Node], final: Optional[Iterable[Node]] = None):
        self.steps: Tuple[Node, ...] = check_nodes('Flow', steps)
        self.final: Tuple[Node, ...] = check_nodes('Flow.final', final or ())

    def run(self, task: Any) -> None:
        """依次执行所有步骤，最后执行 ``final``。

        Args:
          task: 任务实例。
        """
        error: Optional[BaseException] = None
        try:
            run_steps(task, self.steps)
        except BaseException as exc:
            error = exc
            raise
        finally:
            run_final(task, self.final, error)

    def describe(self) -> str:
        """返回步骤名列表，便于日志与测试断言。"""
        return ' -> '.join(node.name for node in self.steps)
