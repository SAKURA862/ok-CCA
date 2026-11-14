"""寻路：在页面图上找代价最小的跳转序列。

默认 Dijkstra（``heuristic`` 恒为 0）；``heuristic`` 参数留给将来升级 A*。
边代价为 ``cost × (1 + 0.5 × fails)``，失败过的边降权但不永久废弃。
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from src.nav.model import Edge, NavError, NavGraph

DEFAULT_MAX_HOPS = 6
FAIL_PENALTY = 0.5

Heuristic = Callable[[str, str], float]


class NavUnreachable(NavError):
    """找不到满足约束的路径。"""


def edge_cost(edge: Edge, fails: int = 0) -> float:
    """计算单条边的有效代价。

    Args:
      edge: 边。
      fails: 该边的累计失败次数。

    Returns:
      含失败惩罚的代价。
    """
    return edge.cost * (1.0 + FAIL_PENALTY * max(0, fails))


@dataclass(frozen=True)
class Path:
    """一条路径。

    Attributes:
      edges: 依次经过的边。
      cost: 路径总代价。
    """

    edges: tuple[Edge, ...]
    cost: float

    @property
    def page_ids(self) -> tuple[str, ...]:
        """依次经过的页面 id，含起点与终点。"""
        if not self.edges:
            return ()
        return (self.edges[0].source,) + tuple(edge.target for edge in self.edges)

    def __len__(self) -> int:
        return len(self.edges)

    def describe(self) -> str:
        """返回 ``home -> arena`` 形式的描述。"""
        return ' -> '.join(self.page_ids) if self.edges else '(空路径)'


def find_path(graph: NavGraph, start: str, goal: str, *,
              fails: Mapping[str, int] | None = None,
              hits: Mapping[str, int] | None = None,
              disabled: Iterable[str] = (),
              heuristic: Heuristic | None = None,
              max_hops: int = DEFAULT_MAX_HOPS) -> Path:
    """在图上寻找最优路径。

    Args:
      graph: 页面图。
      start: 起始页面 id。
      goal: 目标页面 id。
      fails: 按边 key 统计的失败次数，用于降权。
      hits: 按边 key 统计的命中次数，仅用于同代价时排序。
      disabled: 本轮禁用的边 key。
      heuristic: 启发函数，缺省为 Dijkstra。
      max_hops: 最大跳数。

    Returns:
      最优 ``Path``；起终点相同时返回空路径。

    Raises:
      NavUnreachable: 无可用路径或超过 ``max_hops``。
    """
    if start == goal:
        return Path(edges=(), cost=0.0)

    graph.page(start)
    graph.page(goal)

    fails = fails or {}
    hits = hits or {}
    blocked = set(disabled)
    h = heuristic or (lambda _page, _goal: 0.0)

    # 队列元素: (f, g, hops, tie, seq, node, path)，seq 保证比较停在 node 之前。
    counter = 0
    queue: list[tuple[float, float, int, int, int, str, tuple[Edge, ...]]] = [
        (h(start, goal), 0.0, 0, 0, 0, start, ())
    ]
    best_g: dict[str, float] = {start: 0.0}

    while queue:
        _f, g, hops, _tie, _seq, node, path = heapq.heappop(queue)
        if node == goal:
            return Path(edges=path, cost=g)
        if hops >= max_hops:
            continue

        for edge in graph.edges_from(node):
            if edge.key in blocked:
                continue
            next_hops = hops + 1
            if next_hops > max_hops:
                continue
            next_g = g + edge_cost(edge, fails.get(edge.key, 0))
            known = best_g.get(edge.target)
            if known is not None and known <= next_g:
                continue
            best_g[edge.target] = next_g
            counter += 1
            heapq.heappush(queue, (
                next_g + h(edge.target, goal),
                next_g,
                next_hops,
                -hits.get(edge.key, 0),
                counter,
                edge.target,
                path + (edge,),
            ))

    raise NavUnreachable(
        f'{graph.source or graph.profile}: 找不到 {start} -> {goal} 的路径'
        f'（max_hops={max_hops}，禁用 {len(blocked)} 条边）')
