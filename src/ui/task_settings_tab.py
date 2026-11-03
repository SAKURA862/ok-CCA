"""任务设定页：左侧任务列表卡 + 右侧任务详情/配置卡。

右侧卡片是纯静态布局（不继承 ExpandSettingCard，也就没有展开动画）：
- title 区域：左侧图标，图标右侧上下两行是任务名称与任务描述；
- title 区域最右侧是「加入一键日常」开关（与首页卡片上的勾选共用状态）；
- title 下方按任务的 config_type 自动生成文本框、数字框、下拉、开关、多选等配置项，
  改完立即写入 configs/<任务类名>.json，底部可以「恢复默认」。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    NavigationItemPosition,
    PushButton,
    StrongBodyLabel,
    SwitchButton,
    isDarkTheme,
    themeColor,
)

from ok import og
from ok.ui.qt.Communicate import communicate
from ok.ui.qt.tasks.ConfigItemFactory import config_widget
from ok.ui.qt.widget.Tab import Tab
from src.ui import daily_state
from src.ui import theme
from src.ui.cards import (
    PAGE_PADDING,
    SHADOW_PAD,
    RoundedCard,
    divider_color,
    muted_color,
    task_icon,
    title_font,
)

LIST_WIDTH = 250


class TaskRow(RoundedCard):
    """左侧任务列表中的一行：任务图标 + 任务名称。"""

    clicked = Signal(object)

    def __init__(self, task, parent=None):
        super().__init__(parent, radius=10, hoverable=True, shadow=False)
        self.task = task
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(48)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        layout.addWidget(task_icon(task, 26, self), 0, Qt.AlignVCenter)
        label = BodyLabel(task.name, self)
        label.setWordWrap(False)
        layout.addWidget(label, 1, Qt.AlignVCenter)

    def _apply_style(self, *args):
        # 选中：浅底 + 主题色描边；其它：跟随当前主题的 hover 色
        if getattr(self, '_selected', False):
            self.bg_color = theme.color('selected_bg')
            self.border_color = theme.color('accent')
        else:
            self.bg_color = None
            self.border_color = None
        self.hover_color = theme.color('hover_bg')
        self.update()

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.task)


class TaskDetailCard(RoundedCard):
    """右侧任务详情卡片（标题区 + 右上角开关 + 自动生成的配置项）。"""

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task
        self._rows = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            SHADOW_PAD + 20, SHADOW_PAD + 16, SHADOW_PAD + 20, SHADOW_PAD + 16
        )
        layout.setSpacing(10)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_divider())
        layout.addLayout(self._build_config())

    # ------------------------------------------------------------------ 头部
    def _build_header(self):
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        header.addWidget(task_icon(self.task, 44, self), 0, Qt.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        name = StrongBodyLabel(self.task.name, self)
        name.setFont(title_font(14, bold=True))
        text_layout.addWidget(name)
        description = CaptionLabel(self.task.description or '', self)
        description.setWordWrap(True)
        description.setTextColor(muted_color(), muted_color())
        text_layout.addWidget(description)
        header.addLayout(text_layout, 1)

        switch_layout = QVBoxLayout()
        switch_layout.setContentsMargins(0, 0, 12, 0)
        switch_layout.setSpacing(0)
        self.daily_switch = SwitchButton(self)
        self.daily_switch.setOnText(self.tr('开'))
        self.daily_switch.setOffText(self.tr('关'))
        self.daily_switch.setChecked(daily_state.is_in_daily(self.task))
        self.daily_switch.checkedChanged.connect(self._on_daily_changed)
        switch_label = CaptionLabel(self.tr('加入一键日常'), self)
        switch_label.setTextColor(muted_color(), muted_color())
        switch_layout.addWidget(self.daily_switch, 0, Qt.AlignRight)
        switch_layout.addWidget(switch_label, 0, Qt.AlignRight)
        header.addLayout(switch_layout, 0)
        return header

    def _build_divider(self):
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setStyleSheet(f'color: {divider_color().name()}; background-color: {divider_color().name()}; max-height: 1px;')
        return line

    # ------------------------------------------------------------------ 配置
    def _build_config(self):
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 4, 0, 0)
        rows.setSpacing(6)

        config_type = getattr(self.task, 'config_type', None) or {}
        descriptions = getattr(self.task, 'config_description', None) or {}
        defaults = getattr(self.task, 'default_config', None) or {}
        hidden = set()
        for key, value in config_type.items():
            if isinstance(value, dict) and value.get('hidden'):
                hidden.add(key)
                hidden.update(value.get('sub_configs') or [])

        for key in defaults:
            if key.startswith('_') or key in hidden:
                continue
            try:
                widget = config_widget(
                    config_type, descriptions, self.task.config, key,
                    self.task.config.get_default(key), self.task,
                )
            except Exception:  # noqa: BLE001 - 单个配置项失败不影响整页
                continue
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            rows.addWidget(widget)
            self._rows.append(widget)

        if not self._rows:
            hint = CaptionLabel(self.tr('该任务没有可配置项'), self)
            hint.setTextColor(muted_color(), muted_color())
            rows.addWidget(hint)
        else:
            reset = PushButton(self.tr('恢复默认'), self)
            reset.clicked.connect(self._restore_defaults)
            button_row = QHBoxLayout()
            button_row.setContentsMargins(0, 6, 0, 0)
            button_row.addStretch(1)
            button_row.addWidget(reset)
            rows.addLayout(button_row)
        return rows

    def _restore_defaults(self):
        defaults = getattr(self.task, 'default_config', None) or {}
        for key in defaults:
            if key.startswith('_'):
                continue
            try:
                self.task.config[key] = self.task.config.get_default(key)
            except Exception:  # noqa: BLE001
                continue
        for widget in self._rows:
            update = getattr(widget, 'update_value', None)
            if callable(update):
                try:
                    update()
                except Exception:  # noqa: BLE001
                    pass

    def _on_daily_changed(self, checked):
        daily_state.set_in_daily(self.task, checked)


class TaskSettingsTab(Tab):
    """左侧导航第二项：任务设定。"""

    name = '任务设定'
    icon = FluentIcon.EDIT
    position = NavigationItemPosition.SCROLL
    add_after_default_tabs = False

    def __init__(self):
        super().__init__()
        # 内容左右各留 40px（卡片自带 8px 阴影留白，布局边距减掉这一层）
        side = PAGE_PADDING - SHADOW_PAD
        self.vBoxLayout.setContentsMargins(side, side, side, 16)
        self._rows = []
        self._current_task = None
        self._detail_card = None
        self._build()
        daily_state.signals.changed.connect(self._refresh_daily_state)
        communicate.task_list_updated.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        body = QWidget(self)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(max(20 - 2 * SHADOW_PAD, 0))

        self.list_card = RoundedCard(body)
        self.list_card.setFixedWidth(LIST_WIDTH + 2 * SHADOW_PAD)
        self.list_layout = QVBoxLayout(self.list_card)
        self.list_layout.setContentsMargins(
            SHADOW_PAD + 14, SHADOW_PAD + 16, SHADOW_PAD + 14, SHADOW_PAD + 16
        )
        self.list_layout.setSpacing(8)
        list_title = StrongBodyLabel(self.tr('任务列表'), self.list_card)
        list_title.setFont(title_font(13, bold=True))
        self.list_layout.addWidget(list_title)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self.list_layout.addLayout(self.rows_layout)
        self.list_layout.addStretch(1)
        body_layout.addWidget(self.list_card, 0, Qt.AlignTop)

        self.detail_host = QWidget(body)
        self.detail_layout = QVBoxLayout(self.detail_host)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(0)
        self.detail_layout.setAlignment(Qt.AlignTop)
        body_layout.addWidget(self.detail_host, 1)

        self.add_widget(body, 1)

    # ------------------------------------------------------------------ 刷新
    def refresh(self):
        tasks = [task for task in og.executor.onetime_tasks
                 if getattr(task, 'visible', True)]
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []
        for task in tasks:
            row = TaskRow(task, self.list_card)
            row.clicked.connect(self.select_task)
            self.rows_layout.addWidget(row)
            self._rows.append(row)

        if self._current_task not in tasks:
            self._current_task = tasks[0] if tasks else None
        if self._current_task is None:
            self._render_detail(None)
        else:
            self.select_task(self._current_task)

    def select_task(self, task):
        if task is None:
            return
        self._current_task = task
        for row in self._rows:
            row.set_selected(row.task is task)
        self._render_detail(task)

    def _render_detail(self, task):
        # 整个详情区清空重建，避免旧的 stretch / 卡片残留在布局里把新卡片挤到中间
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._detail_card = None
        if task is None:
            hint = CaptionLabel(self.tr('暂无任务'), self.detail_host)
            hint.setTextColor(muted_color(), muted_color())
            self.detail_layout.addWidget(hint, 0, Qt.AlignTop)
            self.detail_layout.addStretch(1)
            return
        card = TaskDetailCard(task, self.detail_host)
        self.detail_layout.addWidget(card, 0, Qt.AlignTop)
        self.detail_layout.addStretch(1)
        self._detail_card = card

    def _refresh_daily_state(self):
        if self._detail_card is not None:
            self._detail_card.daily_switch.setChecked(
                daily_state.is_in_daily(self._detail_card.task)
            )

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
