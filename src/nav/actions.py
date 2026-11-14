"""把边上的动作落到设备上。

只做「点一下」这件事，不关心跳转是否成功——验证由 ``Navigator`` 负责。
"""

from __future__ import annotations

from typing import Callable

from src.nav.model import ACTION_CLICK_POINT, ACTION_CLICK_TEMPLATE, ACTION_KEY, Action

ClickTemplate = Callable[[str, tuple[float, float, float, float] | None], bool]
ClickPoint = Callable[[float, float], None]
PressKey = Callable[[str], None]


class ActionError(RuntimeError):
    """动作无法执行（例如模板没找到）。"""


class ActionExecutor:
    """按 ``Action.type`` 分发到具体设备操作。

    Args:
      click_template: 点模板，签名 ``(template, roi) -> 是否点到``。
      click_point: 点归一化坐标，签名 ``(x, y)``。
      press_key: 按键，签名 ``(key)``。
    """

    def __init__(self, *, click_template: ClickTemplate, click_point: ClickPoint,
                 press_key: PressKey) -> None:
        self._click_template = click_template
        self._click_point = click_point
        self._press_key = press_key

    def run(self, action: Action, *, point: tuple[float, float] | None = None) -> None:
        """执行一个动作。

        Args:
          action: 待执行动作。
          point: 覆盖 ``click_point`` 的运行时坐标（支持动态目标）。

        Raises:
          ActionError: 动作为点模板但模板未匹配到。
        """
        if action.type == ACTION_CLICK_TEMPLATE:
            if not self._click_template(action.template, action.roi):
                raise ActionError(f'模板未匹配到: {action.template}')
            return

        if action.type == ACTION_CLICK_POINT:
            coordinates = point or action.point
            if not coordinates:
                raise ActionError('click_point 缺少坐标')
            self._click_point(coordinates[0], coordinates[1])
            return

        if action.type == ACTION_KEY:
            self._press_key(action.key)
            return

        raise ActionError(f'未知动作类型: {action.type}')
