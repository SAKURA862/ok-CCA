"""编排原语：``Step`` 与流程异常。"""

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Tuple, Union

# 语法糖字段：构造时转成对应的动作对象
SUGAR_FIELDS = ('click', 'click_point', 'key')
# 失败后的处理方式
ON_FAIL_CHOICES = ('retry', 'skip', 'abort')

Point = Union[Sequence[float], Callable[[Any], Sequence[float]]]


class FlowError(RuntimeError):
    """编排层的基类异常。"""


class FlowConfigError(FlowError, ValueError):
    """步骤或状态定义不合法。"""


class FlowFailed(FlowError):
    """步骤执行失败且不再重试。"""


@dataclass(frozen=True)
class Step:
    """一步动作。

    Attributes:
      name: 步骤名，用于日志与失败截图。
      goto: 执行前先导航到的页面 id。
      action: 输入动作对象，例如 ``Tap(template='x')``。
      click: 语法糖，等价于 ``Tap(template=...)``。
      click_point: 语法糖，归一化坐标或返回坐标的函数。
      key: 语法糖，等价于 ``KeyPress(...)``。
      call: 自定义函数，返回值写入 ``task.data[name]``。
      wait: 动作后必须出现的模板名。
      expect: 额外的断言函数，返回 False 视为失败。
      retry: 失败后的重试次数，0 表示只执行一次。
      on_fail: 重试用尽后的处理：``retry`` / ``skip`` / ``abort``。
      optional: 为 True 时，失败只记警告并继续。
    """

    name: str
    goto: Optional[str] = None
    action: Any = None
    click: Optional[str] = None
    click_point: Optional[Point] = None
    key: Optional[str] = None
    call: Optional[Callable[[Any], Any]] = None
    wait: Optional[str] = None
    expect: Optional[Callable[[Any], bool]] = None
    retry: int = 1
    on_fail: str = 'abort'
    optional: bool = False

    def __post_init__(self):
        if not str(self.name or '').strip():
            raise FlowConfigError('Step 需要非空的 name')
        sugars = [field for field in SUGAR_FIELDS if getattr(self, field) is not None]
        if len(sugars) > 1:
            raise FlowConfigError(
                f'Step {self.name!r} 只能有一个语法糖字段，当前为 {sugars}')
        if self.action is not None and sugars:
            raise FlowConfigError(
                f'Step {self.name!r} 不能同时给 action 与 {sugars}')
        if self.action is not None and self.call is not None:
            raise FlowConfigError(f'Step {self.name!r} 的 action 与 call 互斥')
        if self.action is None and not sugars and self.call is None and not self.goto:
            raise FlowConfigError(f'Step {self.name!r} 需要 action、call 或 goto')
        if sugars:
            object.__setattr__(self, 'action', self._sugar_action(sugars[0]))
        if self.on_fail not in ON_FAIL_CHOICES:
            raise FlowConfigError(
                f'Step {self.name!r} 的 on_fail 只能是 {ON_FAIL_CHOICES}，当前为 {self.on_fail!r}')
        if int(self.retry) < 0:
            raise FlowConfigError(f'Step {self.name!r} 的 retry 不能为负')

    def _sugar_action(self, field: str) -> Any:
        """把语法糖字段转成动作对象。"""
        from src.flow import actions

        if field == 'click':
            return actions.Tap(template=self.click)
        if field == 'click_point':
            return actions.Tap(point=self.click_point)
        return actions.KeyPress(self.key)

    @property
    def attempts(self) -> int:
        """含首次执行在内的总尝试次数。"""
        return int(self.retry) + 1

    def describe(self) -> str:
        """返回用于日志的一行描述。"""
        if self.action is not None:
            return f'{self.name}({self.action.describe()})'
        if self.call is not None:
            func = getattr(self.call, '__name__', repr(self.call))
            return f'{self.name}(call={func})'
        return f'{self.name}(goto={self.goto})'


@dataclass(frozen=True)
class Transition:
    """状态机的一条转移规则。

    Attributes:
      guard: 判断函数，入参是任务；返回 True 时走向 ``target``。
      target: 目标状态名。
    """

    guard: Callable[[Any], bool]
    target: str


Guard = Tuple[Callable[[Any], bool], str]
