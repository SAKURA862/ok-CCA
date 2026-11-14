"""页面图的不可变模型：页面（节点）与有向跳转（边）。

图只描述「怎么认页」与「怎么走」，运行期状态（上次页面、命中/失败次数）
另存于 ``configs/nav_cache.json``。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ACTION_CLICK_TEMPLATE = 'click_template'
ACTION_CLICK_POINT = 'click_point'
ACTION_KEY = 'key'
ACTION_TYPES = (ACTION_CLICK_TEMPLATE, ACTION_CLICK_POINT, ACTION_KEY)

DEFAULT_TIMEOUT = 8.0
DEFAULT_RETRIES = 1
DEFAULT_COST = 1.0
MIN_TIMEOUT = 0.5


class NavError(RuntimeError):
    """导航层异常基类。"""


class NavConfigError(NavError):
    """图配置静态错误。"""


class NavUnknownPage(NavError):
    """无法识别当前页面，或引用了不存在的页面。"""


def _fail(source: str, where: str, message: str) -> NavConfigError:
    prefix = f'{source}: ' if source else ''
    return NavConfigError(f'{prefix}{where} {message}')


def _as_mapping(raw: Any, source: str, where: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise _fail(source, where, f'应为对象，实际是 {type(raw).__name__}')
    return raw


def _as_list(raw: Any, source: str, where: str) -> Sequence[Any]:
    if not isinstance(raw, list):
        raise _fail(source, where, f'应为数组，实际是 {type(raw).__name__}')
    return raw


def _as_str(raw: Any, source: str, where: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise _fail(source, where, '应为非空字符串')
    return raw.strip()


def _as_bool(raw: Any, source: str, where: str) -> bool:
    if not isinstance(raw, bool):
        raise _fail(source, where, f'应为布尔值，实际是 {type(raw).__name__}')
    return raw


def _as_number(raw: Any, source: str, where: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _fail(source, where, f'应为数字，实际是 {type(raw).__name__}')
    return float(raw)


def _as_int(raw: Any, source: str, where: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise _fail(source, where, f'应为整数，实际是 {type(raw).__name__}')
    return raw


def _ratio_tuple(raw: Any, source: str, where: str, size: int) -> tuple[float, ...]:
    values = _as_list(raw, source, where)
    if len(values) != size:
        raise _fail(source, where, f'应有 {size} 个数字，实际 {len(values)} 个')
    numbers = tuple(_as_number(value, source, f'{where}[{index}]') for index, value in enumerate(values))
    for number in numbers:
        if not 0.0 <= number <= 1.0:
            raise _fail(source, where, f'坐标应归一化到 0-1，实际 {number}')
    return numbers


@dataclass(frozen=True)
class Action:
    """边上的一次动作。

    Attributes:
      type: ``click_template``、``click_point`` 或 ``key``。
      template: 模板名，仅 ``click_template`` 使用。
      roi: 归一化搜索区域 ``(x1, y1, x2, y2)``，可选。
      point: 归一化坐标 ``(x, y)``，仅 ``click_point`` 使用。
      key: 按键名，仅 ``key`` 使用。
    """

    type: str
    template: str = ''
    roi: tuple[float, float, float, float] | None = None
    point: tuple[float, float] | None = None
    key: str = ''

    @classmethod
    def from_dict(cls, raw: Any, *, source: str = '', where: str = 'action') -> 'Action':
        """从 JSON 对象构造，字段非法时抛 ``NavConfigError``。"""
        data = _as_mapping(raw, source, where)
        action_type = data.get('type')
        if action_type not in ACTION_TYPES:
            raise _fail(source, where, f'type 必须是 {"/".join(ACTION_TYPES)} 之一，实际 {action_type!r}')

        if action_type == ACTION_CLICK_TEMPLATE:
            template = _as_str(data.get('template'), source, f'{where}.template')
            roi = None
            if data.get('roi') is not None:
                box = _ratio_tuple(data.get('roi'), source, f'{where}.roi', 4)
                if not (box[0] < box[2] and box[1] < box[3]):
                    raise _fail(source, f'{where}.roi', '应满足 x1 < x2 且 y1 < y2')
                roi = (box[0], box[1], box[2], box[3])
            return cls(type=action_type, template=template, roi=roi)

        if action_type == ACTION_CLICK_POINT:
            point = _ratio_tuple(data.get('point'), source, f'{where}.point', 2)
            return cls(type=action_type, point=(point[0], point[1]))

        return cls(type=action_type, key=_as_str(data.get('key'), source, f'{where}.key'))

    def to_dict(self) -> dict[str, Any]:
        """转回 JSON 对象，省略空字段。"""
        data: dict[str, Any] = {'type': self.type}
        if self.type == ACTION_CLICK_TEMPLATE:
            data['template'] = self.template
            if self.roi is not None:
                data['roi'] = list(self.roi)
        elif self.type == ACTION_CLICK_POINT:
            data['point'] = list(self.point or ())
        else:
            data['key'] = self.key
        return data

    def describe(self) -> str:
        """返回适合日志的一句话描述。"""
        if self.type == ACTION_CLICK_TEMPLATE:
            suffix = f' roi={self.roi}' if self.roi else ''
            return f'click_template({self.template}{suffix})'
        if self.type == ACTION_CLICK_POINT:
            return f'click_point{tuple(self.point or ())}'
        return f'key({self.key})'


@dataclass(frozen=True)
class Page:
    """图上的一个页面。

    Attributes:
      id: 唯一标识，任务用它声明入口页。
      name: 展示名。
      anchors: 锚点模板名，当前恒为 1 个，保留数组以便将来支持多锚点与判定。
      is_home: 是否为家页，全图恰好一个。
      tags: 检索标签。
    """

    id: str
    name: str
    anchors: tuple[str, ...]
    is_home: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, raw: Any, *, source: str = '', where: str = 'page') -> 'Page':
        """从 JSON 对象构造。"""
        data = _as_mapping(raw, source, where)
        page_id = _as_str(data.get('id'), source, f'{where}.id')
        where = f'page[{page_id}]'
        name = _as_str(data.get('name'), source, f'{where}.name')

        anchors_raw = _as_list(data.get('anchors'), source, f'{where}.anchors')
        if not anchors_raw:
            raise _fail(source, f'{where}.anchors', '至少要有一个锚点模板')
        anchors = tuple(_as_str(item, source, f'{where}.anchors[{index}]')
                        for index, item in enumerate(anchors_raw))
        if len(set(anchors)) != len(anchors):
            raise _fail(source, f'{where}.anchors', '存在重复的锚点模板')

        is_home = _as_bool(data['is_home'], source, f'{where}.is_home') if 'is_home' in data else False

        tags_raw = data.get('tags', [])
        tags = tuple(_as_str(item, source, f'{where}.tags[{index}]')
                     for index, item in enumerate(_as_list(tags_raw, source, f'{where}.tags')))

        return cls(id=page_id, name=name, anchors=anchors, is_home=is_home, tags=tags)

    def to_dict(self) -> dict[str, Any]:
        """转回 JSON 对象，省略默认值。"""
        data: dict[str, Any] = {'id': self.id, 'name': self.name, 'anchors': list(self.anchors)}
        if self.is_home:
            data['is_home'] = True
        if self.tags:
            data['tags'] = list(self.tags)
        return data


@dataclass(frozen=True)
class Edge:
    """一条有向跳转。

    Attributes:
      source: 起始页面 id。
      target: 目标页面 id。
      action: 触发这次跳转的动作。
      timeout: 点击后等待目标页锚点的秒数。
      retries: 失败后的额外重试次数。
      cost: 寻路基础代价。
    """

    source: str
    target: str
    action: Action
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    cost: float = DEFAULT_COST

    @property
    def key(self) -> str:
        """运行时状态用的键，形如 ``home>arena``。"""
        return f'{self.source}>{self.target}'

    @classmethod
    def from_dict(cls, raw: Any, *, source: str = '', where: str = 'edge') -> 'Edge':
        """从 JSON 对象构造。"""
        data = _as_mapping(raw, source, where)
        from_page = _as_str(data.get('from'), source, f'{where}.from')
        to_page = _as_str(data.get('to'), source, f'{where}.to')
        where = f'edge[{from_page}>{to_page}]'
        if from_page == to_page:
            raise _fail(source, where, '不允许自环（from 与 to 相同）')

        action = Action.from_dict(data.get('action'), source=source, where=f'{where}.action')

        timeout = DEFAULT_TIMEOUT
        if data.get('timeout') is not None:
            timeout = _as_number(data.get('timeout'), source, f'{where}.timeout')
            if timeout < MIN_TIMEOUT:
                raise _fail(source, f'{where}.timeout', f'不能小于 {MIN_TIMEOUT} 秒')

        retries = DEFAULT_RETRIES
        if data.get('retries') is not None:
            retries = _as_int(data.get('retries'), source, f'{where}.retries')
            if retries < 0:
                raise _fail(source, f'{where}.retries', '不能为负数')

        cost = DEFAULT_COST
        if data.get('cost') is not None:
            cost = _as_number(data.get('cost'), source, f'{where}.cost')
            if cost <= 0:
                raise _fail(source, f'{where}.cost', '必须大于 0')

        return cls(source=from_page, target=to_page, action=action,
                   timeout=timeout, retries=retries, cost=cost)

    def to_dict(self) -> dict[str, Any]:
        """转回 JSON 对象，省略默认值。"""
        data: dict[str, Any] = {
            'from': self.source,
            'to': self.target,
            'action': self.action.to_dict(),
        }
        if self.timeout != DEFAULT_TIMEOUT:
            data['timeout'] = self.timeout
        if self.retries != DEFAULT_RETRIES:
            data['retries'] = self.retries
        if self.cost != DEFAULT_COST:
            data['cost'] = self.cost
        return data


@dataclass(frozen=True)
class NavGraph:
    """一份只读的页面图。

    Attributes:
      profile: 图对应的游戏配置名。
      pages: 全部页面。
      edges: 全部有向边。
      source: 来源（文件路径），仅用于报错。
    """

    profile: str
    pages: tuple[Page, ...]
    edges: tuple[Edge, ...]
    source: str = ''

    @property
    def home(self) -> Page:
        """家页。"""
        for page in self.pages:
            if page.is_home:
                return page
        raise NavConfigError('图里没有 is_home 页面')

    @property
    def page_ids(self) -> tuple[str, ...]:
        """全部页面 id，保持配置顺序。"""
        return tuple(page.id for page in self.pages)

    def has(self, page_id: str) -> bool:
        """页面是否存在。"""
        return any(page.id == page_id for page in self.pages)

    def page(self, page_id: str) -> Page:
        """按键取页面。

        Raises:
          NavUnknownPage: 页面不存在。
        """
        for page in self.pages:
            if page.id == page_id:
                return page
        raise NavUnknownPage(
            f'{self.source or self.profile}: 没有页面 {page_id!r}，已知页面 {list(self.page_ids)}')

    def edges_from(self, page_id: str) -> tuple[Edge, ...]:
        """从某页出发的全部边。"""
        return tuple(edge for edge in self.edges if edge.source == page_id)

    def edge_between(self, source: str, target: str) -> Edge | None:
        """两页之间的边，没有则返回 None。"""
        for edge in self.edges:
            if edge.source == source and edge.target == target:
                return edge
        return None

    def pages_with_anchor(self, anchor: str) -> tuple[Page, ...]:
        """使用某锚点的页面，用于排查锚点冲突。"""
        return tuple(page for page in self.pages if anchor in page.anchors)

    def to_dict(self) -> dict[str, Any]:
        """转回可序列化的 JSON 结构。"""
        return {
            'profile': self.profile,
            'pages': [page.to_dict() for page in self.pages],
            'edges': [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, raw: Any, *, profile: str = '', source: str = '') -> 'NavGraph':
        """校验并构造页面图。

        Args:
          raw: 解析后的 JSON 对象。
          profile: 配置名，缺省取 ``raw['profile']``。
          source: 来源标识，用于错误信息。

        Returns:
          校验通过的 ``NavGraph``。

        Raises:
          NavConfigError: 任何静态错误。
        """
        data = _as_mapping(raw, source, 'root')

        profile = profile or str(data.get('profile') or '').strip()
        if not profile:
            raise _fail(source, 'root.profile', '缺少 profile（或者从文件名推断）')

        pages_raw = _as_list(data.get('pages'), source, 'pages')
        if not pages_raw:
            raise _fail(source, 'pages', '至少要有一个页面')

        pages = tuple(Page.from_dict(item, source=source, where=f'pages[{index}]')
                      for index, item in enumerate(pages_raw))

        seen: set[str] = set()
        for page in pages:
            if page.id in seen:
                raise _fail(source, f'page[{page.id}]', 'id 重复')
            seen.add(page.id)

        home_pages = [page for page in pages if page.is_home]
        if not home_pages:
            if len(pages) == 1:
                pages = (Page(id=pages[0].id, name=pages[0].name,
                              anchors=pages[0].anchors, is_home=True,
                              tags=pages[0].tags),)
            else:
                raise _fail(source, 'pages', '需要恰好一个页面设置 is_home: true')
        elif len(home_pages) > 1:
            names = ', '.join(page.id for page in home_pages)
            raise _fail(source, 'pages', f'只能有一个 is_home 页面，实际有 {names}')

        edges_raw = _as_list(data.get('edges', []), source, 'edges')
        edges: list[Edge] = []
        seen_edges: set[str] = set()
        for index, item in enumerate(edges_raw):
            edge = Edge.from_dict(item, source=source, where=f'edges[{index}]')
            if not any(page.id == edge.source for page in pages):
                raise _fail(source, f'edge[{edge.key}]', f'from 指向不存在的页面 {edge.source!r}')
            if not any(page.id == edge.target for page in pages):
                raise _fail(source, f'edge[{edge.key}]', f'to 指向不存在的页面 {edge.target!r}')
            if edge.key in seen_edges:
                raise _fail(source, f'edge[{edge.key}]', '重复定义（同一对 from/to 只能有一条边）')
            seen_edges.add(edge.key)
            edges.append(edge)

        return cls(profile=profile, pages=pages, edges=tuple(edges), source=source)


def load_graph(path: str | Path, *, profile: str = '') -> NavGraph:
    """从 JSON 文件加载页面图。

    Args:
      path: 图文件路径。
      profile: 配置名，缺省取文件内字段或文件名。

    Returns:
      校验通过的 ``NavGraph``。

    Raises:
      NavConfigError: 文件不存在、JSON 非法或校验失败。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise NavConfigError(f'导航图不存在: {file_path}')
    try:
        raw = json.loads(file_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise NavConfigError(f'{file_path}: JSON 解析失败（第 {exc.lineno} 行第 {exc.colno} 列）: {exc.msg}') from exc
    return NavGraph.from_dict(raw, profile=profile or file_path.stem, source=str(file_path))
