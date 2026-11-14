"""页面定位：先验上次页面，再全量扫描，认不出就报错。

不做模糊兜底——认不出时盲点会把状态推到未知页面，比直接失败更难恢复。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from src.nav.model import NavGraph, NavUnknownPage, Page

Finder = Callable[[str], Any]


@dataclass(frozen=True)
class Located:
    """定位结果。

    Attributes:
      page: 命中的页面。
      anchor: 命中的锚点模板名。
      box: 匹配框，可能为 None。
      full_scan: 是否走了全量扫描。
    """

    page: Page
    anchor: str
    box: Any = None
    full_scan: bool = False

    @property
    def page_id(self) -> str:
        """命中页面的 id。"""
        return self.page.id


class Locator:
    """在固定图上定位当前页面。

    Args:
      graph: 页面图。
      find: 匹配函数，签名 ``find(template) -> box | None``。
      warn: 可选的告警回调。
    """

    def __init__(self, graph: NavGraph, find: Finder, *,
                 warn: Callable[[str], None] | None = None) -> None:
        self.graph = graph
        self._find = find
        self._warn = warn

    def _hit(self, anchor: str) -> Any:
        try:
            return self._find(anchor)
        except Exception as exc:  # noqa: BLE001 - 匹配异常按未命中处理
            if self._warn:
                self._warn(f'锚点 {anchor} 匹配异常，按未命中处理: {type(exc).__name__}: {exc}')
            return None

    def locate(self, last_page: str | None = None) -> Located:
        """定位当前页面。

        Args:
          last_page: 上次所在页面，可为 None。

        Returns:
          命中的 ``Located``。

        Raises:
          NavUnknownPage: 所有锚点都未命中。
        """
        if last_page and self.graph.has(last_page):
            page = self.graph.page(last_page)
            for anchor in page.anchors:
                box = self._hit(anchor)
                if box is not None:
                    return Located(page=page, anchor=anchor, box=box, full_scan=False)

        for page in self._scan_order(last_page):
            for anchor in page.anchors:
                box = self._hit(anchor)
                if box is not None:
                    return Located(page=page, anchor=anchor, box=box, full_scan=True)

        tried = [anchor for page in self.graph.pages for anchor in page.anchors]
        raise NavUnknownPage(
            f'{self.graph.source or self.graph.profile}: 认不出当前页面'
            f'（试过 {len(tried)} 个锚点: {tried}）。请手动回到已知页面后重试。')

    def is_page(self, page_id: str) -> bool:
        """只校验指定页面（用于每跳之后的验证）。"""
        page = self.graph.page(page_id)
        return any(self._hit(anchor) is not None for anchor in page.anchors)

    def anchor_box(self, page_id: str) -> Any:
        """返回指定页面锚点的匹配框，未命中返回 None。"""
        page = self.graph.page(page_id)
        for anchor in page.anchors:
            box = self._hit(anchor)
            if box is not None:
                return box
        return None

    def _scan_order(self, last_page: str | None) -> Iterable[Page]:
        """全量扫描顺序：家页最后，减少整屏相似导致的误判。"""
        pages = [page for page in self.graph.pages if page.id != last_page]
        home_id = self.graph.home.id
        return sorted(pages, key=lambda page: page.id == home_id)
