"""目标解析：把模板名、归一化坐标、框统一解析成屏幕像素坐标。"""

from typing import Any, Callable, Optional, Sequence, Tuple

from src.flow.steps import FlowConfigError, FlowFailed

Point = Tuple[float, float]
BoxSpec = Sequence[float]
NORMALIZED_CENTER = (0.5, 0.5)


def check_target(owner: str, template: Optional[str] = None, point: Any = None,
                 box: Optional[BoxSpec] = None, relative: Point = NORMALIZED_CENTER,
                 optional: bool = False) -> None:
    """校验目标字段的互斥关系。

    Args:
      owner: 出错时用于提示的动作名。
      template: 模板名。
      point: 归一化坐标，或返回坐标的函数。
      box: 像素框 ``(x, y, w, h)``。
      relative: 框内相对位置。
      optional: 为 True 时允许三个字段都不给。

    Raises:
      FlowConfigError: 同时给了多个目标，或给了 ``point`` 又给了 ``relative``。
    """
    picked = [name for name, value in (('template', template), ('point', point), ('box', box))
              if value is not None]
    if optional:
        if len(picked) > 1:
            raise FlowConfigError(f'{owner} 的 template/point/box 最多给一个，当前 {picked}')
    elif len(picked) != 1:
        raise FlowConfigError(f'{owner} 需要且只能给一个 template/point/box，当前 {picked}')
    if point is not None and tuple(relative) != NORMALIZED_CENTER:
        raise FlowConfigError(f'{owner} 使用 point 时不能同时给 relative')
    if template is not None and not str(template).strip():
        raise FlowConfigError(f'{owner} 的 template 不能为空')


def describe_target(template: Optional[str] = None, point: Any = None,
                    box: Optional[BoxSpec] = None,
                    relative: Point = NORMALIZED_CENTER) -> str:
    """返回用于日志的目标描述。"""
    if template is not None:
        center = tuple(relative) == NORMALIZED_CENTER
        return f'template={template}' if center else f'template={template}@{relative[0]},{relative[1]}'
    if box is not None:
        return f'box={tuple(box)}'
    if point is not None:
        return 'point=<callable>' if callable(point) else f'point={tuple(point)}'
    return 'no-target'


def resolve(task: Any, template: Optional[str] = None, point: Any = None,
            box: Optional[BoxSpec] = None, roi: Optional[Sequence[float]] = None,
            relative: Point = NORMALIZED_CENTER, owner: str = 'action') -> Point:
    """把目标解析成屏幕像素坐标。

    Args:
      task: 任务实例，需要 ``find_one``、``box_of_screen``、``width``、``height``。
      template: 模板名，命中后按 ``relative`` 取框内点。
      point: 归一化坐标（两分量都在 0..1 内）或像素坐标，也可以是不可调用函数。
      box: 像素框 ``(x, y, w, h)``，按 ``relative`` 取框内点。
      roi: 模板搜索区域，归一化 ``(x1, y1, x2, y2)``。
      relative: 框内相对位置。
      owner: 出错时用于提示的动作名。

    Returns:
      屏幕像素坐标 ``(x, y)``。

    Raises:
      FlowConfigError: 没有给任何目标。
      FlowFailed: 模板未匹配到。
    """
    if template is not None:
        return _point_in(_find(task, template, roi, owner), relative)
    if box is not None:
        return _point_in(box, relative)
    if point is None:
        raise FlowConfigError(f'{owner} 没有可解析的目标')
    value = point(task) if callable(point) else point
    x, y = float(value[0]), float(value[1])
    if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
        return int(round(task.width * x)), int(round(task.height * y))
    return int(round(x)), int(round(y))


def resolve_spec(task: Any, spec: Any, roi: Optional[Sequence[float]] = None,
                 relative: Point = NORMALIZED_CENTER, owner: str = 'action') -> Point:
    """解析简写目标：字符串当模板名，四元组当框，二元组当坐标，函数先求值。

    Args:
      task: 任务实例。
      spec: 目标简写。
      roi: 模板搜索区域，仅模板名生效。
      relative: 框内相对位置。
      owner: 出错时用于提示的动作名。

    Returns:
      屏幕像素坐标 ``(x, y)``。
    """
    if isinstance(spec, str):
        return resolve(task, template=spec, roi=roi, relative=relative, owner=owner)
    if callable(spec):
        return resolve_spec(task, spec(task), roi=roi, relative=relative, owner=owner)
    values = list(spec)
    if len(values) == 4:
        return resolve(task, box=values, relative=relative, owner=owner)
    if len(values) == 2:
        return resolve(task, point=values, owner=owner)
    raise FlowConfigError(f'{owner} 的目标简写只支持模板名、二元组、四元组，当前 {spec!r}')


def describe_spec(spec: Any) -> str:
    """返回简写目标的描述。"""
    if isinstance(spec, str):
        return f'template={spec}'
    if callable(spec):
        return 'target=<callable>'
    values = tuple(spec)
    return f'box={values}' if len(values) == 4 else f'point={values}'


def _find(task: Any, template: str, roi: Optional[Sequence[float]], owner: str) -> Any:
    box_arg = None
    if roi is not None:
        box_of_screen = getattr(task, 'box_of_screen', None)
        if callable(box_of_screen):
            box_arg = box_of_screen(*roi)
    threshold = float(getattr(task, 'nav_settings', {}).get('threshold', 0.8))
    found = task.find_one(template, box=box_arg, threshold=threshold)
    if found is None:
        raise FlowFailed(f'{owner} 模板未匹配: {template}')
    return found


def _point_in(box: Any, relative: Point) -> Point:
    x, y, width, height = _box_tuple(box)
    return (int(round(x + width * relative[0])), int(round(y + height * relative[1])))


def _box_tuple(box: Any) -> Tuple[float, float, float, float]:
    if all(hasattr(box, attr) for attr in ('x', 'y', 'width', 'height')):
        return float(box.x), float(box.y), float(box.width), float(box.height)
    values = list(box)
    if len(values) != 4:
        raise FlowConfigError(f'box 需要 4 个分量 (x, y, w, h)，当前 {values}')
    return float(values[0]), float(values[1]), float(values[2]), float(values[3])


TargetSpec = Callable[[Any], Any]
