"""导航执行：按寻路结果逐跳点击，并用目标页锚点验证每一跳。

每一跳都是「动作 → 等目标页出现」；失败按边的 ``retries`` 重试，
同一条边连续失败两次就在本轮禁用，避免在同一条死路上反复消耗时间。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from src.nav.actions import ActionExecutor, ActionError
from src.nav.model import Edge, NavGraph, NavUnknownPage
from src.nav.router import Path as NavPath, find_path

DISABLE_AFTER_FAILURES = 2


class NavStepFailed(RuntimeError):
    """某一跳执行后没有到达目标页。"""


@dataclass
class NavCache:
    """跨运行保存的边统计，用于降权与死路标记。

    Attributes:
      path: 缓存文件路径。
      transitions: 边 key 到 ``{hits, fails, last}`` 的映射。
    """

    path: Path | None = None
    transitions: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None) -> 'NavCache':
        """读取缓存；文件不存在或损坏时返回空缓存。"""
        if not path:
            return cls()
        file_path = Path(path)
        data: dict[str, Any] = {}
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                data = {}
        transitions = data.get('transitions') if isinstance(data, dict) else None
        return cls(path=file_path, transitions=dict(transitions or {}))

    def save(self) -> None:
        """写回缓存文件；写入失败不影响导航。"""
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({'transitions': self.transitions}, ensure_ascii=False, indent=2),
                encoding='utf-8')
        except OSError:
            pass

    def hits(self, key: str) -> int:
        """某条边的累计成功次数。"""
        return int(self.transitions.get(key, {}).get('hits', 0))

    def fails(self, key: str) -> int:
        """某条边的累计失败次数。"""
        return int(self.transitions.get(key, {}).get('fails', 0))

    def record(self, key: str, ok: bool, at: str) -> None:
        """记录一次跳转结果。"""
        entry = dict(self.transitions.get(key, {'hits': 0, 'fails': 0}))
        entry['hits' if ok else 'fails'] = int(entry.get('hits' if ok else 'fails', 0)) + 1
        entry['last'] = at
        self.transitions[key] = entry

    def fails_map(self) -> dict[str, int]:
        """全部边的失败次数。"""
        return {key: int(value.get('fails', 0)) for key, value in self.transitions.items()}

    def hits_map(self) -> dict[str, int]:
        """全部边的成功次数。"""
        return {key: int(value.get('hits', 0)) for key, value in self.transitions.items()}


class Navigator:
    """在固定图上做「从这里走到那里」。

    Args:
      graph: 页面图。
      locate: 无参定位函数，返回 ``Located``。
      wait_page: ``(page_id, timeout) -> bool``，等待目标页出现。
      actions: 动作执行器。
      cache: 边统计缓存。
      screenshot: ``(name) -> None``，失败取证。
      warn: 告警回调。
      clock: 时间源，测试可注入。
      max_hops: 单次寻路的最大跳数。
    """

    def __init__(self, graph: NavGraph, *, locate: Callable[[], Any],
                 wait_page: Callable[[str, float], bool], actions: ActionExecutor,
                 cache: NavCache | None = None,
                 screenshot: Callable[[str], None] | None = None,
                 warn: Callable[[str], None] | None = None,
                 clock: Callable[[], float] = time.time,
                 max_hops: int = 6) -> None:
        self.graph = graph
        self._locate = locate
        self._wait_page = wait_page
        self._actions = actions
        self._cache = cache or NavCache()
        self._screenshot = screenshot
        self._warn = warn or (lambda _message: None)
        self._clock = clock
        self._max_hops = max_hops
        self._last_page: str | None = None
        self._history: list[str] = []
        self._fail_streak: dict[str, int] = {}
        self._disabled: set[str] = set()

    @property
    def last_page(self) -> str | None:
        """上一次到达的页面 id。"""
        return self._last_page

    @property
    def history(self) -> tuple[str, ...]:
        """本次运行走过的页面序列。"""
        return tuple(self._history)

    def locate(self) -> str:
        """识别当前页面并记录为 ``last_page``。"""
        page_id = self._locate().page_id
        self._last_page = page_id
        return page_id

    def goto(self, target: str, *, start: str | None = None) -> NavPath:
        """走到目标页。

        Args:
          target: 目标页面 id。
          start: 起始页面，缺省用 ``last_page``，再缺省现场识别。

        Returns:
          实际走过的路径；已经在目标页时返回空路径。

        Raises:
          NavUnknownPage: 目标页不存在。
          NavUnreachable: 图上无路径。
          NavStepFailed: 某一跳重试后仍未到达。
        """
        if not self.graph.has(target):
            raise NavUnknownPage(f'{self.graph.profile}: 没有页面 {target!r}')

        current = start or self._last_page or self.locate()
        self._remember(current)
        if current == target:
            self._last_page = target
            return NavPath(edges=(), cost=0.0)

        path = self._travel(current, target)
        for edge in path.edges:
            self._remember(edge.target)
        return path

    def ensure(self, target: str) -> NavPath:
        """确保位于目标页；已在目标页时不走图。"""
        current = self._last_page or self.locate()
        return NavPath(edges=(), cost=0.0) if current == target else self.goto(target, start=current)

    def back(self) -> str | None:
        """返回上一个停留过的页面，历史为空时返回 None。"""
        if len(self._history) < 2:
            return None
        self._history.pop()
        previous = self._history[-1]
        current = self._last_page or self.locate()
        if current != previous:
            self._travel(current, previous)
        self._last_page = previous
        return previous

    def _travel(self, current: str, target: str) -> NavPath:
        path = find_path(self.graph, current, target,
                         fails=self._cache.fails_map(),
                         hits=self._cache.hits_map(),
                         disabled=self._disabled,
                         max_hops=self._max_hops)
        for edge in path.edges:
            self._run_edge(edge)
        self._cache.save()
        return path

    def _remember(self, page: str) -> None:
        if not self._history or self._history[-1] != page:
            self._history.append(page)

    def _run_edge(self, edge: Edge) -> None:
        attempts = edge.retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._actions.run(edge.action)
            except ActionError as exc:
                last_error = exc
                self._warn(f'{edge.key}: 第 {attempt}/{attempts} 次动作失败: {exc}')
                continue

            if self._wait_page(edge.target, edge.timeout):
                self._on_success(edge)
                return
            last_error = NavStepFailed(f'{edge.timeout:.1f}s 内没有到达 {edge.target}')
            self._warn(f'{edge.key}: 第 {attempt}/{attempts} 次未到达 {edge.target}')

        self._on_failure(edge)
        raise NavStepFailed(f'{edge.key} 跳转失败: {last_error}')

    def _on_success(self, edge: Edge) -> None:
        self._cache.record(edge.key, True, self._now())
        self._fail_streak.pop(edge.key, None)
        self._disabled.discard(edge.key)
        self._last_page = edge.target

    def _on_failure(self, edge: Edge) -> None:
        self._cache.record(edge.key, False, self._now())
        streak = self._fail_streak.get(edge.key, 0) + 1
        self._fail_streak[edge.key] = streak
        if streak >= DISABLE_AFTER_FAILURES:
            self._disabled.add(edge.key)
            self._warn(f'{edge.key}: 连续失败 {streak} 次，本轮禁用')
        if self._screenshot:
            self._screenshot(f'nav_step_failed_{edge.source}_{edge.target}')

    def _now(self) -> str:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._clock()))
