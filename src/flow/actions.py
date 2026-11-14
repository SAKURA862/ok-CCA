"""输入动作：把「怎么动手指、键盘」封装成可复用的对象。

动作只负责产生外部输入，不返回业务数据；读数据请用 ``Step.call``。
每个动作都支持三种目标：``template``（模板名）、``point``（归一化坐标）、
``box``（像素框），三者只能给一个，由 :mod:`src.flow.targets` 统一解析。
"""

from dataclasses import dataclass
from typing import Any, Optional, Sequence, Tuple

from src.flow import targets
from src.flow.steps import FlowConfigError

# 短按与长按的分界（秒）
LONG_HOLD_THRESHOLD = 0.15
DEFAULT_TAP_HOLD = 0.01
DEFAULT_LONG_HOLD = 1.0
DEFAULT_SWIPE_DURATION = 0.5
DEFAULT_DRAG_DURATION = 0.6
DEFAULT_DRAG_HOLD = 0.2
DRAG_STEPS = 6
DEFAULT_DOUBLE_INTERVAL = 0.12
TEXT_SETTLE = 0.4
COMBO_HOLD = 0.05

Point = Tuple[float, float]


@dataclass(frozen=True)
class _Targeted:
    """带单个目标字段的动作基类。

    Attributes:
      template: 模板名。
      point: 归一化坐标，或返回坐标的函数。
      box: 像素框 ``(x, y, w, h)``。
      roi: 模板搜索区域，归一化 ``(x1, y1, x2, y2)``。
      relative: 框内相对位置。
    """

    template: Optional[str] = None
    point: Any = None
    box: Optional[Sequence[float]] = None
    roi: Optional[Sequence[float]] = None
    relative: Point = targets.NORMALIZED_CENTER
    TARGET_REQUIRED = True

    def __post_init__(self):
        targets.check_target(type(self).__name__, template=self.template, point=self.point,
                             box=self.box, relative=self.relative,
                             optional=not self.TARGET_REQUIRED)

    def resolve(self, task: Any) -> Point:
        """解析出屏幕像素坐标。"""
        return targets.resolve(task, template=self.template, point=self.point, box=self.box,
                               roi=self.roi, relative=self.relative,
                               owner=type(self).__name__)

    def describe(self) -> str:
        """返回用于日志的目标描述。"""
        return targets.describe_target(template=self.template, point=self.point, box=self.box,
                                       relative=self.relative)


@dataclass(frozen=True)
class _TwoTargeted:
    """带起点与终点两个目标的动作基类。

    Attributes:
      start: 起点简写，模板名 / 二元组 / 四元组 / 函数。
      end: 终点简写，同 ``start``。
      start_roi: 起点模板的搜索区域。
      end_roi: 终点模板的搜索区域。
      start_relative: 起点框内相对位置。
      end_relative: 终点框内相对位置。
    """

    start: Any
    end: Any
    start_roi: Optional[Sequence[float]] = None
    end_roi: Optional[Sequence[float]] = None
    start_relative: Point = targets.NORMALIZED_CENTER
    end_relative: Point = targets.NORMALIZED_CENTER

    def __post_init__(self):
        if self.start is None or self.end is None:
            raise FlowConfigError(f'{type(self).__name__} 需要 start 与 end')

    def resolve_start(self, task: Any) -> Point:
        """解析起点坐标。"""
        return targets.resolve_spec(task, self.start, roi=self.start_roi,
                                    relative=self.start_relative, owner=type(self).__name__)

    def resolve_end(self, task: Any) -> Point:
        """解析终点坐标。"""
        return targets.resolve_spec(task, self.end, roi=self.end_roi,
                                    relative=self.end_relative, owner=type(self).__name__)

    def describe(self) -> str:
        """返回用于日志的目标描述。"""
        return f'{targets.describe_spec(self.start)} -> {targets.describe_spec(self.end)}'


@dataclass(frozen=True)
class Tap(_Targeted):
    """单击目标。"""

    def run(self, task: Any) -> None:
        """执行单击。"""
        x, y = self.resolve(task)
        task.click(x, y)


@dataclass(frozen=True)
class DoubleTap(_Targeted):
    """双击目标。

    Attributes:
      interval: 两次点击的间隔（秒）。
    """

    interval: float = DEFAULT_DOUBLE_INTERVAL

    def run(self, task: Any) -> None:
        """执行双击。"""
        x, y = self.resolve(task)
        task.click(x, y)
        task.sleep(self.interval)
        task.click(x, y)


@dataclass(frozen=True)
class LongPress(_Targeted):
    """长按目标。

    Attributes:
      hold: 按住时长（秒）。
    """

    hold: float = DEFAULT_LONG_HOLD

    def run(self, task: Any) -> None:
        """执行长按。"""
        x, y = self.resolve(task)
        _press(task, x, y, self.hold)


@dataclass(frozen=True)
class RightTap(_Targeted):
    """右键点击目标，仅对支持右键的交互方式生效。"""

    def run(self, task: Any) -> None:
        """执行右键点击。"""
        x, y = self.resolve(task)
        task.click(x, y, key='right')


@dataclass(frozen=True)
class Swipe(_TwoTargeted):
    """匀速滑动，保留惯性。

    Attributes:
      duration: 手势时长（秒）。
    """

    duration: float = DEFAULT_SWIPE_DURATION

    def run(self, task: Any) -> None:
        """执行滑动。"""
        from_x, from_y = self.resolve_start(task)
        to_x, to_y = self.resolve_end(task)
        task.swipe(from_x, from_y, to_x, to_y, duration=self.duration)


@dataclass(frozen=True)
class Drag(_TwoTargeted):
    """拖动：分段移动并在抬起前停住，用于精确对齐。

    Attributes:
      duration: 移动阶段总时长（秒）。
      hold: 抬起前的停顿（秒）。
    """

    duration: float = DEFAULT_DRAG_DURATION
    hold: float = DEFAULT_DRAG_HOLD

    def run(self, task: Any) -> None:
        """执行拖动。"""
        start = self.resolve_start(task)
        end = self.resolve_end(task)
        _drag(task, start, end, self.duration, self.hold)


@dataclass(frozen=True)
class KeyPress:
    """按键；``hold`` 大于阈值时按长按处理。

    Attributes:
      key: 键名，例如 ``escape``。
      hold: 按住时长（秒）。
    """

    key: str
    hold: float = 0.02

    def __post_init__(self):
        if not str(self.key or '').strip():
            raise FlowConfigError('KeyPress 需要非空的 key')

    def run(self, task: Any) -> None:
        """发送按键。"""
        if self.hold > LONG_HOLD_THRESHOLD:
            task.send_key_down(self.key)
            task.sleep(self.hold)
            task.send_key_up(self.key)
        else:
            task.send_key(self.key, down_time=self.hold)

    def describe(self) -> str:
        """返回用于日志的描述。"""
        return f'key={self.key} hold={self.hold}'


@dataclass(frozen=True)
class KeyCombo:
    """组合键：依次按下，再逆序抬起。

    Attributes:
      keys: 键名序列。
      hold: 全部按下后的停留时长（秒）。
    """

    keys: Sequence[str]
    hold: float = COMBO_HOLD

    def __post_init__(self):
        if len(tuple(self.keys)) < 2:
            raise FlowConfigError('KeyCombo 至少需要两个键')

    def run(self, task: Any) -> None:
        """发送组合键。"""
        keys = tuple(self.keys)
        for key in keys:
            task.send_key_down(key)
            task.sleep(COMBO_HOLD)
        task.sleep(self.hold)
        for key in reversed(keys):
            task.send_key_up(key)

    def describe(self) -> str:
        """返回用于日志的描述。"""
        return f'combo={"+".join(self.keys)}'


@dataclass(frozen=True)
class TextInput:
    """输入文本；给了目标时先点击目标再输入。

    Attributes:
      text: 要输入的文本，仅支持 ASCII，空格会转成 ``%s``。
      template: 可选，先点击的模板名。
      point: 可选，先点击的归一化坐标。
      box: 可选，先点击的像素框。
      roi: 模板搜索区域。
      relative: 框内相对位置。
      settle: 点击目标到开始输入之间的等待（秒）。
    """

    text: str
    template: Optional[str] = None
    point: Any = None
    box: Optional[Sequence[float]] = None
    roi: Optional[Sequence[float]] = None
    relative: Point = targets.NORMALIZED_CENTER
    settle: float = TEXT_SETTLE

    def __post_init__(self):
        targets.check_target('TextInput', template=self.template, point=self.point,
                             box=self.box, relative=self.relative, optional=True)
        if not self.text:
            raise FlowConfigError('TextInput 需要非空的 text')
        if not all(32 <= ord(char) <= 126 for char in self.text):
            raise FlowConfigError('TextInput 只支持 ASCII，中文请用剪贴板或输入法方案')

    def run(self, task: Any) -> None:
        """点击目标（可选）后输入文本。"""
        if self.template is not None or self.point is not None or self.box is not None:
            x, y = targets.resolve(task, template=self.template, point=self.point, box=self.box,
                                   roi=self.roi, relative=self.relative, owner='TextInput')
            task.click(x, y)
            task.sleep(self.settle)
        task.input_text(self.text.replace(' ', '%s'))

    def describe(self) -> str:
        """返回用于日志的描述。"""
        target = targets.describe_target(template=self.template, point=self.point,
                                         box=self.box, relative=self.relative)
        return f'text={self.text!r} {target}'


def _press(task: Any, x: int, y: int, hold: float) -> None:
    """在坐标处按住 ``hold`` 秒，优先使用 motionevent。"""
    if _use_motionevent(task):
        task.adb_shell('input', 'motionevent', 'DOWN', int(x), int(y))
        task.sleep(hold)
        task.adb_shell('input', 'motionevent', 'UP', int(x), int(y))
        return
    task.mouse_down(int(x), int(y))
    task.sleep(hold)
    task.mouse_up()


def _drag(task: Any, start: Point, end: Point, duration: float, hold: float) -> None:
    """分段拖到终点，停住 ``hold`` 秒后抬起。"""
    if not _use_motionevent(task):
        task.swipe(start[0], start[1], end[0], end[1], duration=duration, settle_time=hold)
        return
    task.adb_shell('input', 'motionevent', 'DOWN', int(start[0]), int(start[1]))
    step_sleep = max(duration, 0.0) / DRAG_STEPS
    for index in range(1, DRAG_STEPS + 1):
        ratio = index / DRAG_STEPS
        x = int(round(start[0] + (end[0] - start[0]) * ratio))
        y = int(round(start[1] + (end[1] - start[1]) * ratio))
        task.sleep(step_sleep)
        task.adb_shell('input', 'motionevent', 'MOVE', x, y)
    task.sleep(hold)
    task.adb_shell('input', 'motionevent', 'UP', int(end[0]), int(end[1]))


def _use_motionevent(task: Any) -> bool:
    """判断是否可以用 ``adb shell input motionevent`` 做分段手势。"""
    return callable(getattr(task, 'adb_shell', None))
