"""按 profile 缓存页面图，避免每跳都读盘与校验。"""

from __future__ import annotations

from pathlib import Path

from src.nav.model import NavGraph, load_graph

_graphs: dict[str, NavGraph] = {}


def get(profile: str, path: str | Path | None = None) -> NavGraph:
    """取某个 profile 的页面图，首次调用时加载。

    Args:
      profile: 配置名，同时作为缓存键。
      path: 图文件路径，缺省为 ``assets/nav/<profile>.json``。

    Returns:
      页面图。
    """
    cached = _graphs.get(profile)
    if cached is not None:
        return cached
    file_path = Path(path) if path else Path('assets') / 'nav' / f'{profile}.json'
    graph = load_graph(file_path, profile=profile)
    _graphs[profile] = graph
    return graph


def reset(profile: str | None = None) -> None:
    """清空缓存；``profile`` 为 None 时清空全部。"""
    if profile is None:
        _graphs.clear()
    else:
        _graphs.pop(profile, None)
