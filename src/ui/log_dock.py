"""底边栏日志：右下角悬浮按钮 + 从内容区底部展开的实时日志面板。

按钮与面板都挂在主窗口这一层，所以切换任何页面都还在。

面板用「预留空间」的方式占位：展开时把 `stackedWidget` 的最大高度按面板高度收窄，
再把面板放到空出来的底部条带里。这样页面是真正让出高度的（不会遮挡内容），
同时不动 `stackedWidget` 的父子关系——重挂父控件会让页面内的鼠标事件路由失效。
"""

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRect, QSize, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from qfluentwidgets import ComboBox, FluentIcon, StrongBodyLabel, ToolButton, isDarkTheme, themeColor

from ok import Logger

from src.ui import log_bus, theme
from src.ui.cards import divider_color

logger = Logger.get_logger(__name__)

BUTTON_SIZE = 44
BUTTON_MARGIN = 20
PANEL_HEIGHT = 220
ANIM_MS = 180
UNLIMITED = 16777215

_dock = None


def install(window):
    """主窗口就绪后调用一次；重复调用返回同一个实例。"""
    global _dock
    if _dock is not None:
        return _dock
    try:
        _dock = LogDock(window)
    except Exception as error:  # noqa: BLE001 - 底边栏失败不能影响主界面
        logger.exception(f'install log dock failed: {error}')
        _dock = None
    return _dock


class LogDock(QObject):

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._expanded = False
        self._reserve = 0
        self._base_margins = (0, 0, 0, 0)
        layout = getattr(window, 'widgetLayout', None)
        if layout is not None:
            self._base_margins = tuple(layout.getContentsMargins())
        self._panel = self._build_panel()
        self._button = self._build_button()

        self._anim = QPropertyAnimation(self._panel, b'maximumHeight', self)
        self._anim.setDuration(ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda value: self._reserve_space(int(value)))
        self._anim.finished.connect(self._on_anim_finished)

        window.installEventFilter(self)
        log_bus.settings_changed.changed.connect(self._apply_enabled)
        theme.signals.changed.connect(self._restyle)

        self._apply_enabled()
        self._restyle_panel()
        QTimer.singleShot(400, self._reposition)
        QTimer.singleShot(1500, self._reposition)

    # ------------------------------------------------------------------ 构建
    def _build_panel(self):
        panel = QWidget(self._window)
        panel.setObjectName('logDockPanel')
        panel.setMaximumHeight(0)
        panel.setVisible(False)
        panel.setAutoFillBackground(True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(40, 10, 40, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = StrongBodyLabel('运行日志', panel)
        header.addWidget(title)
        header.addStretch(1)

        self._level_box = ComboBox(panel)
        self._level_box.addItems(log_bus.LEVELS)
        self._level_box.setFixedWidth(108)
        self._level_box.setCurrentIndex(self._current_level_index())
        self._level_box.currentTextChanged.connect(self._on_level_changed)
        header.addWidget(self._level_box)

        clear = ToolButton(FluentIcon.DELETE, panel)
        clear.setToolTip(self.tr('清空'))
        clear.clicked.connect(self._clear)
        header.addWidget(clear)

        collapse = ToolButton(FluentIcon.CHEVRON_DOWN_MED, panel)
        collapse.setToolTip(self.tr('收起'))
        collapse.clicked.connect(self._collapse)
        header.addWidget(collapse)
        layout.addLayout(header)

        self.view = log_bus.LogView(panel, max_lines=log_bus.DOCK_MAX_LINES, compact=True)
        self.view.set_level(str(log_bus.SETTINGS.get('level') or 'INFO'))
        layout.addWidget(self.view, 1)
        return panel

    def _build_button(self):
        button = QToolButton(self._window)
        button.setObjectName('logDockButton')
        button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        button.setIconSize(QSize(20, 20))
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(self.tr('运行日志'))
        button.clicked.connect(self._toggle)
        button.hide()
        self._restyle_button(button)
        return button

    # ------------------------------------------------------------------ 显示
    def _apply_enabled(self):
        enabled = bool(log_bus.SETTINGS.get('dock_enabled'))
        if not enabled:
            self._collapse()
        self._button.setVisible(enabled)
        if enabled:
            self._reposition()

    def _current_level_index(self) -> int:
        level = str(log_bus.SETTINGS.get('level') or 'INFO').upper()
        return log_bus.LEVELS.index(level) if level in log_bus.LEVELS else 1

    def _toggle(self):
        if self._expanded:
            self._collapse()
        else:
            self._expand()

    def _expand(self):
        self._expanded = True
        self._panel.setVisible(True)
        self._panel.setMaximumHeight(max(self._reserve, 1))
        self._anim.stop()
        self._anim.setStartValue(max(self._reserve, 0))
        self._anim.setEndValue(PANEL_HEIGHT)
        self._anim.start()
        self._button.setIcon(FluentIcon.DOWN.icon())
        self._reposition()

    def _collapse(self):
        self._expanded = False
        self._button.setIcon(FluentIcon.UP.icon())
        if not self._panel.isVisible():
            self._reserve_space(0)
            return
        self._anim.stop()
        self._anim.setStartValue(max(self._reserve, 0))
        self._anim.setEndValue(0)
        self._anim.start()

    def _on_anim_finished(self):
        if not self._expanded:
            self._panel.setVisible(False)
        self._reposition()

    # ------------------------------------------------------------------ 布局
    def _content_rect(self) -> QRect:
        """内容区的完整矩形（不受当前预留高度影响）。"""
        stacked = self._window.stackedWidget
        top_left = stacked.mapTo(self._window, QPoint(0, 0))
        return QRect(top_left, QSize(stacked.width(), stacked.height() + self._reserve))

    def _reserve_space(self, height: int):
        """把内容区底部让出 height 像素给日志面板。"""
        rect = self._content_rect()
        height = max(0, min(int(height), max(0, rect.height() - 120)))
        self._reserve = height
        stacked = self._window.stackedWidget
        layout = getattr(self._window, 'widgetLayout', None)
        if layout is not None:
            # 用布局底边距占位：页面从顶部开始填满剩余高度，不会像设最大高度那样被居中。
            left, top, right, bottom = self._base_margins
            layout.setContentsMargins(left, top, right, bottom + height)
        if height <= 0:
            stacked.setMaximumHeight(UNLIMITED)
        else:
            stacked.setMaximumHeight(UNLIMITED)
        if height > 0:
            self._panel.setGeometry(rect.left(), rect.top() + rect.height() - height,
                                    rect.width(), height)
            self._panel.raise_()
        self._move_button(rect, height)

    def _move_button(self, rect: QRect, reserve: int):
        page_bottom = rect.top() + rect.height() - reserve
        x = rect.right() - BUTTON_MARGIN - BUTTON_SIZE + 1
        y = page_bottom - BUTTON_MARGIN - BUTTON_SIZE + 1
        self._button.move(max(0, x), max(0, y))
        self._button.raise_()

    def _reposition(self):
        try:
            if self._reserve:
                self._reserve_space(self._reserve)
            else:
                rect = self._content_rect()
                self._move_button(rect, 0)
        except Exception:  # noqa: BLE001 - 主窗口还没建好时静默跳过
            return

    def eventFilter(self, obj, event):
        if obj is self._window and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            QTimer.singleShot(0, self._reposition)
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ 其他
    def _on_level_changed(self, text: str):
        log_bus.SETTINGS['level'] = text
        self.view.set_level(text)

    def _clear(self):
        log_bus.bus.clear()
        self.view.clear()

    def _restyle(self):
        self._restyle_button(self._button)
        self._restyle_panel()
        self._panel.update()

    def _restyle_panel(self):
        palette = theme.palette()
        self._panel.setStyleSheet(
            'QWidget#logDockPanel {'
            f' background-color: {palette.page_bg};'
            f' border-top: 1px solid {divider_color().name()};'
            '}'
        )

    def _restyle_button(self, button):
        palette = theme.palette()
        accent = themeColor().name()
        background = palette.card_bg if isDarkTheme() else '#FFFFFF'
        button.setStyleSheet(
            'QToolButton {'
            f' background-color: {background};'
            f' border: 1px solid {divider_color().name()};'
            ' border-radius: 12px;'
            '}'
            'QToolButton:hover {'
            f' border: 1px solid {accent};'
            '}'
            'QToolButton:pressed {'
            f' background-color: {palette.selected_bg};'
            '}'
        )
        button.setIcon((FluentIcon.DOWN if self._expanded else FluentIcon.UP).icon())
