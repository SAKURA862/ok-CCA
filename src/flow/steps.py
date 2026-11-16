"""编排原语：``Step``、``Stop`` 与流程异常。"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence, Tuple, Union

# 语法糖字段：构造时转成对应的动作对象，名字与动作类一一对应
SUGAR_FIELDS = ('click', 'double_click', 'right_click', 'long_press', 'key_press')
# 已移除的旧字段：保留形参只为给出迁移提示
LEGACY_FIELDS = ('click_point', 'key')
# 失败后的处理方式
ON_FAIL_CHOICES = ('retry', 'skip', 'abort')

Point = Union[Sequence[float], Callable[[Any], Sequence[float]]]
Target = Union[str, Sequence[float], Callable[[Any], Any]]


class FlowError(RuntimeError):
    """编排层的基类异常。"""


class FlowConfigError(FlowError, ValueError):
    """步骤或状态定义不合法。"""


class FlowFailed(FlowError):
    """步骤执行失败且不再重试。"""


class TargetMissing(FlowFailed):
    """动作目标未匹配：确定性失败，不进入重试。"""


class FlowAborted(FlowFailed):
    """流程被 ``Stop`` 主动终止。"""


@dataclass(frozen=True)
class Step:
    """一步动作。

    Attributes:
      name: 步骤名，用于日志与失败截图；同一容器内唯一。
      goto: 执行前先导航到的页面 id。
      action: 输入动作对象，例如 ``Click('x')``。
      click: 语法糖，等价于 ``Click(target)``，target 可为模板/坐标/框/lambda。
      double_click: 语法糖，等价于 ``DoubleClick(target)``。
      right_click: 语法糖，等价于 ``RightClick(target)``。
      long_press: 语法糖，等价于 ``LongPress(target)``，hold 取默认值。
      key_press: 语法糖，等价于 ``KeyPress(key)``。
      call: 自定义函数，返回值写入 ``task.data[name]``。
      wait: 动作后必须出现的模板名，可给多个（任一出现即算成功）。
      wait_timeout: 单次等待模板的上限（秒），默认 2；页面跳转可调大到 8。
      retry_delay: 两次尝试之间的固定间隔（秒），默认 0.3。
      expect: 额外的断言函数，返回 False 视为失败。
      retry: 失败后的重试次数，0 表示只执行一次。
      on_fail: 重试用尽后的处理：``retry`` / ``skip`` / ``abort``。
      optional: 为 True 时，失败只记警告并继续。
      when: 执行前的守卫，返回 False 时跳过整步（不算失败）。
    """

    name: str
    goto: Optional[str] = None
    action: Any = None
    click: Optional[Target] = None
    double_click: Optional[Target] = None
    right_click: Optional[Target] = None
    long_press: Optional[Target] = None
    key_press: Optional[str] = None
    call: Optional[Callable[[Any], Any]] = None
    wait: Optional[str] = None
    wait_timeout: float = 2.0
    retry_delay: float = 0.3
    expect: Optional[Callable[[Any], bool]] = None
    retry: int = 5
    on_fail: str = 'abort'
    optional: bool = False
    when: Optional[Callable[[Any], bool]] = None
    # 迁移占位，禁止使用
    click_point: Any = field(default=None, repr=False, compare=False)
    key: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if not str(self.name or '').strip():
            raise FlowConfigError('Step 需要非空的 name')
        for legacy in LEGACY_FIELDS:
            if getattr(self, legacy) is not None:
                raise FlowConfigError(
                    f'Step {self.name!r} 的 {legacy!r} 已移除：'
                    f'坐标请写 click=(x, y)，按键请写 key_press="..."')
        sugars = [field_name for field_name in SUGAR_FIELDS
                  if getattr(self, field_name) is not None]
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

    def _sugar_action(self, field_name: str) -> Any:
        """把语法糖字段转成动作对象。"""
        from src.flow import actions

        target = getattr(self, field_name)
        if field_name == 'click':
            return actions.Click(target)
        if field_name == 'double_click':
            return actions.DoubleClick(target)
        if field_name == 'right_click':
            return actions.RightClick(target)
        if field_name == 'long_press':
            return actions.LongPress(target)
        return actions.KeyPress(str(target))

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
class Stop:
    """伪步骤：执行到这里主动结束流程，``final`` 仍会执行。

    Attributes:
      reason: 终止原因，会写进日志与 ``FlowAborted`` 消息。
    """

    reason: str = 'stopped'

    @property
    def name(self) -> str:
        """步骤名，供容器统一记录。"""
        return 'stop'

    def describe(self) -> str:
        """返回用于日志的一行描述。"""
        return f'stop({self.reason})'


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
