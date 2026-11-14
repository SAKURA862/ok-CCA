"""页面图导航：节点（页面）与边（跳转）。

对外只需要 :func:`load_graph` 与 :class:`NavGraph`，其余模块（定位、寻路、执行）
都建立在这份不可变的图上。
"""

from src.nav.locator import Located, Locator  # noqa: F401
from src.nav.model import (  # noqa: F401
    ACTION_CLICK_POINT,
    ACTION_CLICK_TEMPLATE,
    ACTION_KEY,
    ACTION_TYPES,
    Action,
    Edge,
    NavConfigError,
    NavError,
    NavGraph,
    NavUnknownPage,
    Page,
    load_graph,
)
from src.nav.router import NavUnreachable, Path, edge_cost, find_path  # noqa: F401

__all__ = [
    'ACTION_CLICK_POINT',
    'ACTION_CLICK_TEMPLATE',
    'ACTION_KEY',
    'ACTION_TYPES',
    'Action',
    'Edge',
    'Located',
    'Locator',
    'NavConfigError',
    'NavError',
    'NavGraph',
    'NavUnknownPage',
    'NavUnreachable',
    'Page',
    'Path',
    'edge_cost',
    'find_path',
    'load_graph',
]
