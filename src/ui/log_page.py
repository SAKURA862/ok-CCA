"""侧边栏「日志」页：状态条 + 实时日志 + 底边栏开关。

- 状态条给生产环境用户看：当前在跑什么、跑了多久、设备连没连上。
- 日志区给开发和用户排障用：级别过滤、暂停吸底、清空、导出。
- 底部设置卡控制「启用底边栏日志」，状态存在 configs/UiLog.json。
"""

import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    FluentIcon,
    NavigationItemPosition,
    PushButton,
    StrongBodyLabel,
    SwitchButton,
)

from ok import Logger, og
from ok.ui.qt.widget.Tab import Tab

from src.ui import log_bus, theme
from src.ui.cards import (
    PAGE_PADDING,
    SHADOW_PAD,
    RoundedCard,
    title_font,
)

logger = Logger.get_logger(__name__)


def _status_text() -> tuple[str, str, str, str]:
    """返回（状态、当前任务、运行时长、设备）四个字符串，任何异常都不影响界面。"""
    executor = getattr(og, 'executor', None)
    state = '空闲'
    task_name = '—'
    duration = '—'
    device = '未知'
    if executor is not None:
        try:
            current = getattr(executor, 'current_task', None)
            if current is not None:
                state = '已暂停' if getattr(executor, 'paused', False) else '运行中'
                task_name = getattr(current, 'name', None) or type(current).__name__
                started = getattr(current, 'start_time', None) or getattr(current, '_start_time', None)
                if started:
                    seconds = max(0, int(time.time() - started))
                    duration = f'{seconds // 60:02d}:{seconds % 60:02d}'
        except Exception:  # noqa: BLE001 - 状态栏只是展示
            pass
        try:
            devices = getattr(getattr(executor, 'device_manager', None), 'device_dict', None) or {}
            online = sum(1 for item in devices.values() if item.get('connected'))
            device = f'已连接 {online} 台' if online else '未连接'
        except Exception:  # noqa: BLE001
            device = '未知'
    return state, str(task_name), duration, device


class LogTab(Tab):
    """左侧导航「日志」页。"""

    name = '日志'
    icon = FluentIcon.DOCUMENT
    position = NavigationItemPosition.SCROLL
    add_after_default_tabs = False

    def __init__(self):
        super().__init__()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side = PAGE_PADDING - SHADOW_PAD
        self.vBoxLayout.setContentsMargins(side, side, side, 16)
        self.vBoxLayout.setSpacing(12)
        self._paused = False
        self._build()
        self._nav_promoted = False
        QTimer.singleShot(1200, self._promote_navigation)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start()
        theme.signals.changed.connect(self._restyle)
        self._refresh_status()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        self.status_card = RoundedCard(self)
        status_layout = QHBoxLayout(self.status_card)
        status_layout.setContentsMargins(
            SHADOW_PAD + 24, SHADOW_PAD + 14, SHADOW_PAD + 24, SHADOW_PAD + 14
        )
        status_layout.setSpacing(48)
        self._status_labels = {}
        for key, caption in (('state', '状态'), ('task', '当前任务'),
                             ('duration', '运行时长'), ('device', '设备')):
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(2)
            label = CaptionLabel(caption, self.status_card)
            label.setTextColor(theme.color('subtext'), theme.color('subtext'))
            value = StrongBodyLabel('—', self.status_card)
            value.setFont(title_font(14, bold=True))
            column.addWidget(label)
            column.addWidget(value)
            status_layout.addLayout(column, 0)
            self._status_labels[key] = value
        status_layout.addStretch(1)
        self.add_widget(self.status_card)

        # 日志工具条
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(SHADOW_PAD, 0, SHADOW_PAD, 0)
        toolbar.setSpacing(10)
        heading = StrongBodyLabel(self.tr('运行日志'), self)
        heading.setFont(title_font(14, bold=True))
        toolbar.addWidget(heading)
        toolbar.addStretch(1)

        self.level_box = ComboBox(self)
        self.level_box.addItems(log_bus.LEVELS)
        self.level_box.setCurrentIndex(self._level_index())
        self.level_box.setFixedWidth(120)
        self.level_box.currentTextChanged.connect(self._on_level_changed)
        toolbar.addWidget(self.level_box)

        self.pause_button = PushButton(FluentIcon.PAUSE, self.tr('暂停'), self)
        self.pause_button.clicked.connect(self._toggle_pause)
        toolbar.addWidget(self.pause_button)

        self.clear_button = PushButton(FluentIcon.DELETE, self.tr('清空'), self)
        self.clear_button.clicked.connect(self._clear)
        toolbar.addWidget(self.clear_button)

        self.export_button = PushButton(FluentIcon.SAVE, self.tr('导出'), self)
        self.export_button.clicked.connect(self._export)
        toolbar.addWidget(self.export_button)
        self.addLayout(toolbar)

        self.log_view = log_bus.LogView(
            self, max_lines=int(log_bus.SETTINGS.get('max_lines') or log_bus.PAGE_MAX_LINES)
        )
        self.add_widget(self.log_view, 1)

        # 底边栏开关
        self.settings_card = RoundedCard(self)
        settings_layout = QHBoxLayout(self.settings_card)
        settings_layout.setContentsMargins(
            SHADOW_PAD + 24, SHADOW_PAD + 14, SHADOW_PAD + 24, SHADOW_PAD + 14
        )
        settings_layout.setSpacing(16)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        switch_title = StrongBodyLabel(self.tr('启用底边栏日志'), self.settings_card)
        switch_title.setFont(title_font(13, bold=True))
        switch_hint = CaptionLabel(self.tr('开启后任意页面右下角都会显示日志按钮'), self.settings_card)
        switch_hint.setTextColor(theme.color('subtext'), theme.color('subtext'))
        text_column.addWidget(switch_title)
        text_column.addWidget(switch_hint)
        settings_layout.addLayout(text_column, 1)

        self.dock_switch = SwitchButton(self.settings_card)
        self.dock_switch.setChecked(bool(log_bus.SETTINGS.get('dock_enabled')))
        self.dock_switch.setOnText(self.tr('开'))
        self.dock_switch.setOffText(self.tr('关'))
        self.dock_switch.checkedChanged.connect(self._on_dock_toggled)
        settings_layout.addWidget(self.dock_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        self.add_widget(self.settings_card)

    # ------------------------------------------------------------------ 交互
    def _level_index(self) -> int:
        level = str(log_bus.SETTINGS.get('level') or 'INFO').upper()
        return log_bus.LEVELS.index(level) if level in log_bus.LEVELS else 1

    def _refresh_status(self):
        state, task_name, duration, device = _status_text()
        for key, value in (('state', state), ('task', task_name),
                           ('duration', duration), ('device', device)):
            label = self._status_labels.get(key)
            if label is not None:
                label.setText(value)

    def _on_level_changed(self, text: str):
        log_bus.SETTINGS['level'] = text
        self.log_view.set_level(text)

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.pause_button.setText(self.tr('继续'))
            self.pause_button.setIcon(FluentIcon.PLAY)
            self.log_view.block_append(True)
        else:
            self.pause_button.setText(self.tr('暂停'))
            self.pause_button.setIcon(FluentIcon.PAUSE)
            self.log_view.block_append(False)

    def _clear(self):
        log_bus.bus.clear()
        self.log_view.clear()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, self.tr('导出日志'), 'ok-script.log',
                                              'Log (*.log *.txt)')
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(log_bus.bus.text())
        except Exception as error:  # noqa: BLE001 - 导出失败只提示
            logger.error(f'export log failed: {error}')

    def _on_dock_toggled(self, checked: bool):
        log_bus.SETTINGS['dock_enabled'] = bool(checked)
        log_bus.settings_changed.changed.emit()

    def _restyle(self):
        for label in getattr(self, '_status_labels', {}).values():
            label.update()

    # ------------------------------------------------------------------ 导航
    def _promote_navigation(self):
        """把「日志」排在「任务设定」之后、「截图方式」之前。"""
        if getattr(self, '_nav_promoted', False):
            return
        window = self.window()
        nav = getattr(window, 'navigationInterface', None)
        route = self.objectName()
        if nav is None or nav.widget(route) is None:
            QTimer.singleShot(300, self._promote_navigation)
            return
        self._nav_promoted = True
        settings_tab = None
        for widget in window.stackedWidget.findChildren(QWidget):
            if type(widget).__name__ == 'TaskSettingsTab':
                settings_tab = widget
                break
        target = 2 if settings_tab is not None else 1
        try:
            nav.removeWidget(route)
            nav.insertItem(target, route, self.icon, window.app.tr(self.name),
                           onClick=lambda *_args: window.switchTo(self),
                           position=NavigationItemPosition.SCROLL)
        except Exception as error:  # noqa: BLE001 - 排序失败不影响功能
            logger.warning(f'log nav reorder skipped: {error}')
