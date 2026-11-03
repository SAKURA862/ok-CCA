"""弹窗层：在取帧路径上拦截随时弹出的窗口。

设计要点（与 `docs/plan/global-runtime-plan.md` 的 P2 对应）：

1. **挂钩位置是 ``next_frame()``**：任何任务想拿到新画面都必须走这里，
   所以不需要每个业务任务写检测代码。
2. **规则驱动**：一条规则 = 模板 + 区域 + 阈值 + 动作 + 冷却 + 次数上限。
   默认规则为空（还没有素材），可从 ``configs/overlays.json`` 追加。
3. **节流**：同一帧路径上两次检查至少间隔 ``min_interval``（默认 0.3s），
   所以正常执行时几乎感觉不到开销；命中后立刻返回，业务会重新取帧。
4. **防死循环**：同一规则连续命中超过 ``max_attempts`` 次就抛
   :class:`OverlayStuck`，并留下 ``overlay_stuck_<id>`` 截图。
5. **触发时机**：``anytime``（取帧时）、``after_login`` / ``on_home``
   （启动层与导航层调用）、``on_stuck``（业务一段时间没有进展时的兜底）。
   ``anytime`` 规则只在 ``anytime`` 检查里执行，避免同一帧被处理两次。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

DEFAULT_MIN_INTERVAL = 0.3
DEFAULT_STUCK_AFTER = 8.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_COOLDOWN = 2.0
DEFAULT_THRESHOLD = 0.8

# 触发时机白名单，写错时机在加载期就能发现
WHEN_CHOICES = ('anytime', 'after_login', 'on_home', 'on_stuck')


class OverlayStuck(RuntimeError):
    """同一弹窗规则反复命中，判定为卡死而不是普通弹窗。"""


@dataclass(frozen=True)
class OverlayRule:
    """一条弹窗规则。"""

    id: str
    when: tuple[str, ...] = ('anytime',)
    template: str = ''
    roi: tuple[float, float, float, float] | None = None
    threshold: float = DEFAULT_THRESHOLD
    action: Mapping[str, Any] = field(default_factory=dict)
    cooldown: float = DEFAULT_COOLDOWN
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    daily: bool = False
    enabled: bool = True

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> 'OverlayRule':
        """从 JSON 字典构造；缺省字段走默认值，写错的时机直接报错。"""
        rule_id = str(raw.get('id') or '').strip()
        if not rule_id:
            raise ValueError('overlay rule 缺少 id')

        when = raw.get('when', 'anytime')
        when = (when,) if isinstance(when, str) else tuple(when)
        unknown = [item for item in when if item not in WHEN_CHOICES]
        if unknown:
            raise ValueError(f'overlay rule {rule_id} 的 when 含未知时机: {unknown}')

        roi = raw.get('roi')
        if roi is not None:
            if len(roi) != 4:
                raise ValueError(f'overlay rule {rule_id} 的 roi 必须是 4 个数')
            roi = tuple(float(value) for value in roi)

        return cls(
            id=rule_id,
            when=when,
            template=str(raw.get('template') or ''),
            roi=roi,
            threshold=float(raw.get('threshold', DEFAULT_THRESHOLD)),
            action=dict(raw.get('action') or {}),
            cooldown=float(raw.get('cooldown', DEFAULT_COOLDOWN)),
            max_attempts=int(raw.get('max_attempts', DEFAULT_MAX_ATTEMPTS)),
            daily=bool(raw.get('daily', False)),
            enabled=bool(raw.get('enabled', True)),
        )


def load_rules(path: str | Path | None = None) -> list[OverlayRule]:
    """读取规则表；文件不存在或为空时返回空表（等价于没有弹窗要处理）。"""
    if not path:
        return []
    file = Path(path)
    if not file.is_file():
        return []
    raw = json.loads(file.read_text(encoding='utf-8') or '[]')
    if isinstance(raw, Mapping):
        raw = raw.get('rules', [])
    return [OverlayRule.from_dict(item) for item in raw]


class OverlayGuard:
    """把规则应用到当前帧上，返回本次处理掉的规则 id。"""

    def __init__(
        self,
        rules: Iterable[OverlayRule] = (),
        *,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.rules = tuple(rule for rule in rules if rule.enabled)
        self.min_interval = max(0.0, float(min_interval))
        self._clock = clock
        self._last_check = float('-inf')
        self._attempts: dict[str, int] = {}
        self._last_fire: dict[str, float] = {}
        self.handled: list[str] = []

    # ------------------------------------------------------------------ 查询
    def rule(self, rule_id: str) -> OverlayRule | None:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None

    def attempts(self, rule_id: str) -> int:
        return self._attempts.get(rule_id, 0)

    def reset(self) -> None:
        """业务确认画面已经干净时调用，清空所有计数。"""
        self._attempts.clear()
        self._last_fire.clear()

    # ------------------------------------------------------------------ 处理
    def process(
        self,
        task,
        frame,
        when: str = 'anytime',
        *,
        daily_pending: bool = False,
    ) -> str | None:
        """检查一帧；命中并执行动作后返回规则 id，否则返回 None。"""
        now = self._clock()
        if now - self._last_check < self.min_interval:
            return None
        self._last_check = now

        for rule in self.rules:
            if not self._matches_when(rule, when):
                continue
            if rule.daily and not daily_pending:
                continue

            box = self._find(task, rule, frame)
            if rule.template and box is None:
                # 这一帧没看到它，说明上一次已经处理干净了
                self._attempts.pop(rule.id, None)
                continue

            if now - self._last_fire.get(rule.id, float('-inf')) < rule.cooldown:
                continue

            attempts = self._attempts.get(rule.id, 0)
            if attempts >= rule.max_attempts:
                self._capture(task, f'overlay_stuck_{rule.id}')
                raise OverlayStuck(
                    f'规则 {rule.id} 已连续命中 {attempts} 次仍未消失（when={when}）'
                )

            self._fire(task, rule, box)
            self._attempts[rule.id] = attempts + 1
            self._last_fire[rule.id] = now
            self.handled.append(rule.id)
            self._info(task, f'overlay: 处理 {rule.id}（第 {attempts + 1} 次）')
            return rule.id

        return None

    # ------------------------------------------------------------------ 内部
    @staticmethod
    def _matches_when(rule: OverlayRule, when: str) -> bool:
        # anytime 规则只服务于取帧路径，避免 on_home/on_stuck 时重复执行
        if 'anytime' in rule.when:
            return when == 'anytime'
        return when in rule.when

    def _find(self, task, rule: OverlayRule, frame):
        if not rule.template:
            return None
        finder = getattr(task, 'find_one', None)
        if not callable(finder):
            return None
        box_arg = None
        if rule.roi:
            box_of_screen = getattr(task, 'box_of_screen', None)
            if callable(box_of_screen):
                box_arg = box_of_screen(*rule.roi)
        try:
            return finder(rule.template, box=box_arg, frame=frame, threshold=rule.threshold)
        except Exception:
            # 模板还没导出、帧为空之类的问题不应该打断业务
            return None

    def _fire(self, task, rule: OverlayRule, box) -> None:
        action = rule.action or {}
        kind = str(action.get('type', 'click_box')).lower()
        if kind == 'click_box':
            if box is None:
                raise ValueError(f'规则 {rule.id} 使用 click_box，但没有匹配到模板')
            task.click(box)
        elif kind == 'click':
            task.click(action['x'], action['y'])
        elif kind == 'key':
            task.send_key(action['key'])
        else:
            raise ValueError(f'规则 {rule.id} 的动作类型未知: {kind}')

    @staticmethod
    def _capture(task, name: str) -> None:
        shot = getattr(task, 'screenshot', None)
        if not callable(shot):
            return
        try:
            shot(name=name)
        except Exception:
            pass

    @staticmethod
    def _info(task, message: str) -> None:
        logger = getattr(task, 'log_info', None)
        if callable(logger):
            logger(message)
