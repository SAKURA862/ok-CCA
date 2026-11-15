"""循环驱动器：把一组步骤重复到条件满足或次数用尽。"""

from typing import Any, Callable, Iterable, Optional, Tuple

from src.flow.flow import check_nodes, run_final, run_steps
from src.flow.steps import FlowConfigError, FlowFailed

EXHAUSTED_CHOICES = ('abort', 'warn')


class Loop:
    """重复执行一组步骤，直到 ``until`` 为真或达到次数上限。

    Attributes:
      steps: 每轮执行的步骤序列。
      until: 每轮结束后的判定函数，返回 True 时停止。
      times: 最多执行多少轮。
      on_exhausted: 次数用尽后的处理：``abort`` 抛错，``warn`` 只记警告。
      final: 无论正常结束还是异常都会执行的收尾步骤。
    """

    def __init__(self, steps: Iterable[Any], *, until: Optional[Callable[[Any], bool]] = None,
                 times: int = 10, on_exhausted: str = 'abort',
                 final: Optional[Iterable[Any]] = None):
        self.steps: Tuple[Any, ...] = check_nodes('Loop', steps)
        self.final: Tuple[Any, ...] = check_nodes('Loop.final', final or ())
        self.until = until
        self.times = int(times)
        self.on_exhausted = on_exhausted
        if self.times <= 0:
            raise FlowConfigError('Loop.times 必须为正')
        if on_exhausted not in EXHAUSTED_CHOICES:
            raise FlowConfigError(
                f'Loop.on_exhausted 只能是 {EXHAUSTED_CHOICES}，当前为 {on_exhausted!r}')

    def run(self, task: Any) -> int:
        """执行循环。

        Args:
          task: 任务实例。

        Returns:
          实际执行的轮数。

        Raises:
          FlowFailed: 次数用尽且 ``on_exhausted='abort'``。
        """
        error: Optional[BaseException] = None
        try:
            return self._drive(task)
        except BaseException as exc:
            error = exc
            raise
        finally:
            run_final(task, self.final, error)

    def _drive(self, task: Any) -> int:
        for index in range(1, self.times + 1):
            run_steps(task, self.steps)
            task.log_info(f'flow: 第 {index}/{self.times} 轮结束')
            if self.until is not None and self.until(task):
                return index
        if self.on_exhausted == 'warn':
            task.log_warning(f'flow: 循环执行满 {self.times} 轮')
            return self.times
        raise FlowFailed(f'循环执行满 {self.times} 轮仍未满足结束条件')

    def describe(self) -> str:
        """返回步骤名列表，便于日志与测试断言。"""
        return ' | '.join(node.name for node in self.steps)
