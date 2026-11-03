"""首页：今日日常进度卡 + 今日任务卡片表格。

布局（与需求一致）：
- 顶部一张横向圆角卡片：左侧显示「今日日常还剩 N 项未完成」，右侧「一键完成日常」按钮。
- 下方「今日任务」区域：每个任务一张小卡片，卡片内左上角是任务图标，
  右上角是「加入一键日常」勾选框，下方左对齐显示任务名称。
"""

import threading

from PySide6.QtCore import QTimer, Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    FluentIcon,
    NavigationItemPosition,
    PrimaryPushButton,
    StrongBodyLabel,
)

from ok import og
from ok.ui.qt.Communicate import communicate
from ok.ui.qt.widget.Tab import Tab
from src.ui import daily_state
from src.ui.cards import (
    PAGE_PADDING,
    SHADOW_PAD,
    RingProgress,
    RoundedCard,
    muted_color,
    task_icon,
    title_font,
)

# 任务小卡片：高度固定，宽度随窗口在 [TILE_MIN_WIDTH, ∞) 间伸缩；
# 间距固定 20px，窗口左右内边距 40px（卡片自带 8px 阴影留白，所以要减去）。
TILE_HEIGHT = 104
TILE_MIN_WIDTH = 100
TILE_GAP = 20


def visible_tasks():
    """当前 GUI 可见的一次性任务。"""
    return [task for task in og.executor.onetime_tasks if getattr(task, 'visible', True)]


class DailyRunThread(QThread):
    """在后台依次执行「一键日常」中的任务，避免阻塞界面。"""

    progress = Signal(str, int, int)
    failed = Signal(str)

    def __init__(self, tasks):
        super().__init__()
        self._tasks = list(tasks)

    def run(self):
        launch_task = self._launch_task()
        total = len(self._tasks) + (1 if launch_task else 0)
        if launch_task and self._run_launch_step(launch_task, total):
            return
        offset = 1 if launch_task else 0
        for index, task in enumerate(self._tasks, 1):
            self.progress.emit(task.name, index + offset, total)
            done = threading.Event()

            def on_done(finished_task, _task=task, _done=done):
                if finished_task is _task:
                    _done.set()

            communicate.task_done.connect(on_done)
            try:
                og.app.start_controller.start(task)
                finished = done.wait(timeout=1800)
            except Exception as error:  # noqa: BLE001 - 直接反馈给界面
                self.failed.emit(f'{task.name} 启动失败：{error}')
                return
            finally:
                communicate.task_done.disconnect(on_done)
            if not finished:
                self.failed.emit(f'{task.name} 执行超时')
                return
            daily_state.mark_done(task)

    @staticmethod
    def _launch_task():
        """一键日常开始前，先跑隐藏的启动任务把游戏准备好。"""
        return next(
            (item for item in og.executor.onetime_tasks
             if type(item).__name__ == 'CrossCoreDailyTask'),
            None,
        )

    def _run_launch_step(self, task, total):
        self.progress.emit('启动游戏', 1, total)
        return not self._wait_task(task, timeout=900, label='启动游戏')

    def _wait_task(self, task, timeout, label=None):
        """启动一个任务并等它结束，返回是否正常完成。"""
        name = label or task.name
        done = threading.Event()

        def on_done(finished_task):
            if finished_task is task:
                done.set()

        communicate.task_done.connect(on_done)
        try:
            og.app.start_controller.start(task)
            return done.wait(timeout=timeout)
        except Exception as error:  # noqa: BLE001 - 直接反馈给界面
            self.failed.emit(f'{name} 启动失败：{error}')
            return False
        finally:
            communicate.task_done.disconnect(on_done)


class TaskTile(RoundedCard):
    """首页的单个任务小卡片：图标、勾选框、任务名、今日状态。"""

    clicked = Signal(object)

    def __init__(self, task, parent=None):
        super().__init__(parent, hoverable=True)
        self.task = task
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(TILE_HEIGHT + 2 * SHADOW_PAD)
        # 宽度交给布局按比例分配，拖动窗口时由 Qt 自己实时重算，避免跳变
        self.setMinimumWidth(TILE_MIN_WIDTH + 2 * SHADOW_PAD)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SHADOW_PAD + 10, SHADOW_PAD + 8, SHADOW_PAD + 8, SHADOW_PAD + 8)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.addWidget(task_icon(task, 22, self), 0, Qt.AlignTop | Qt.AlignLeft)
        top.addStretch(1)
        self.checkbox = CheckBox('', self)
        self.checkbox.setFixedSize(20, 20)
        self.checkbox.setToolTip(self.tr('加入一键日常'))
        self.checkbox.setChecked(daily_state.is_in_daily(task))
        self.checkbox.stateChanged.connect(self._on_checked)
        top.addWidget(self.checkbox, 0, Qt.AlignTop | Qt.AlignRight)
        layout.addLayout(top)

        self.name_label = BodyLabel('', self)
        self.name_label.setFont(title_font(11, bold=True))
        self.name_label.setWordWrap(False)
        self.name_label.setToolTip(task.name)
        if daily_state.completed_today(task):
            self.name_label.setStyleSheet(f'color: {muted_color().name()};')
        layout.addWidget(self.name_label)

        self.status_label = CaptionLabel('', self)
        self.status_label.setTextColor(muted_color(), muted_color())
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self._update_status()
        self._update_elide()

    def _update_elide(self):
        available = max(self.width() - 2 * SHADOW_PAD - 20, 24)
        metrics = self.name_label.fontMetrics()
        self.name_label.setText(metrics.elidedText(self.task.name, Qt.ElideRight, available))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elide()

    def _update_status(self):
        if daily_state.completed_today(self.task):
            self.status_label.setText(self.tr('今日已完成'))
            self.setToolTip(self.tr('今日已完成'))
        elif daily_state.is_in_daily(self.task):
            self.status_label.setText(self.tr('待完成'))
            self.setToolTip(self.tr('待完成'))
        else:
            self.status_label.setText(self.tr('未加入日常'))
            self.setToolTip(self.tr('在一键日常之外'))

    def _on_checked(self, _state):
        daily_state.set_in_daily(self.task, self.checkbox.isChecked())
        self._update_status()

    def mouseReleaseEvent(self, event):
        # 点击卡片（勾选框除外，它是子控件会自己吃掉事件）跳转到任务设定页
        if event.button() == Qt.LeftButton and self.card_rect().contains(event.position()):
            self.clicked.emit(self.task)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class HomeTab(Tab):
    """左侧导航第一项：首页。"""

    name = '首页'
    icon = FluentIcon.HOME
    position = NavigationItemPosition.SCROLL
    add_after_default_tabs = False

    def __init__(self):
        super().__init__()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 内容左右各留 40px（卡片自带 8px 阴影留白，所以布局边距减掉这一层）
        side = PAGE_PADDING - SHADOW_PAD
        self.vBoxLayout.setContentsMargins(side, side, side, 16)
        self._run_thread = None
        self._tiles = []
        self._columns_cache = None
        self._build()
        daily_state.signals.changed.connect(self.refresh)
        communicate.task_list_updated.connect(self.refresh)
        communicate.task_done.connect(lambda *_args: self.refresh())
        self.refresh()
        self._nav_promoted = False
        QTimer.singleShot(500, self._promote_navigation)

    # ------------------------------------------------------------------ 构建
    def _build(self):
        self.summary_card = RoundedCard(self)
        summary_layout = QHBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(
            SHADOW_PAD + 24, SHADOW_PAD + 16, SHADOW_PAD + 24, SHADOW_PAD + 16
        )
        summary_layout.setSpacing(20)

        self.ring = RingProgress(self.summary_card, size=92, thickness=9)
        summary_layout.addWidget(self.ring, 0, Qt.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        caption = CaptionLabel(self.tr('今日日常'), self.summary_card)
        caption.setTextColor(muted_color(), muted_color())
        self.summary_label = StrongBodyLabel(self.tr('还剩 0 项'), self)
        self.summary_label.setFont(title_font(20, bold=True))
        self.summary_hint = CaptionLabel(self.tr('在「任务设定」里把任务加入一键日常'), self)
        self.summary_hint.setTextColor(muted_color(), muted_color())
        text_layout.addWidget(caption)
        text_layout.addWidget(self.summary_label)
        text_layout.addWidget(self.summary_hint)
        summary_layout.addLayout(text_layout, 1)

        self.run_button = PrimaryPushButton(FluentIcon.PLAY, self.tr('一键完成日常'), self)
        self.run_button.setFixedHeight(38)
        self.run_button.clicked.connect(self._run_daily)
        summary_layout.addWidget(self.run_button, 0, Qt.AlignVCenter)
        self.add_widget(self.summary_card)

        section = StrongBodyLabel(self.tr('今日任务'), self)
        section.setFont(title_font(14, bold=True))
        self.add_widget(section)

        self.rows_host = QWidget(self)
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(max(TILE_GAP - 2 * SHADOW_PAD, 0))
        self.rows_layout.setAlignment(Qt.AlignTop)
        self.rows_host.setMinimumWidth(0)
        self.add_widget(self.rows_host, 1)

        self.empty_label = CaptionLabel(self.tr('暂无任务'), self)
        self.empty_label.setTextColor(muted_color(), muted_color())
        self.add_widget(self.empty_label)

    # ------------------------------------------------------------------ 刷新
    def _content_width(self) -> int:
        viewport = self.viewport()
        width = viewport.width() if viewport is not None else self.width()
        return max(width - 2 * (PAGE_PADDING - SHADOW_PAD), TILE_MIN_WIDTH + 2 * SHADOW_PAD)

    def _columns(self) -> int:
        """最多能放几列：卡片可见宽度不小于 TILE_MIN_WIDTH。"""
        content = self._content_width()
        gap = max(TILE_GAP - 2 * SHADOW_PAD, 0)
        columns = 1
        while True:
            candidate = columns + 1
            visible = (content - (candidate - 1) * gap) / candidate - 2 * SHADOW_PAD
            if visible >= TILE_MIN_WIDTH:
                columns = candidate
            else:
                break
        return columns

    def _layout_columns(self, total: int) -> int:
        """实际使用的列数：内容能容纳的列数与任务数取小，保证一行排满时左右都对齐。"""
        return max(1, min(self._columns(), total))

    def refresh(self):
        tasks = visible_tasks()
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                continue
            row_layout = item.layout()
            if row_layout is not None:
                while row_layout.count():
                    child = row_layout.takeAt(0)
                    child_widget = child.widget()
                    if child_widget is not None:
                        child_widget.deleteLater()
        self._tiles = []
        columns = self._layout_columns(len(tasks))
        self._columns_cache = columns
        gap = max(TILE_GAP - 2 * SHADOW_PAD, 0)
        for start in range(0, len(tasks), columns):
            chunk = tasks[start:start + columns]
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(gap)
            for task in chunk:
                tile = TaskTile(task, self.rows_host)
                tile.clicked.connect(self._open_task)
                row.addWidget(tile, 1, Qt.AlignTop)
                self._tiles.append(tile)
            # 不足一行的部分留空，卡片宽度仍与整行一致
            empty = columns - len(chunk)
            if empty:
                row.addStretch(empty)
            self.rows_layout.addLayout(row)
        self.empty_label.setVisible(not tasks)

        remaining = daily_state.remaining_tasks(tasks)
        selected = daily_state.selected_tasks(tasks)
        self.ring.set_value(len(selected) - len(remaining), len(selected))
        self.summary_label.setText(self.tr('还剩 {} 项').format(len(remaining)))
        if remaining:
            names = '、'.join(task.name for task in remaining[:3])
            if len(remaining) > 3:
                names += ' 等'
            self.summary_hint.setText(self.tr('待完成：') + names)
        elif selected:
            self.summary_hint.setText(self.tr('今日日常已全部完成'))
        else:
            self.summary_hint.setText(self.tr('在「任务设定」里把任务加入日常'))
        if self._run_thread is None:
            self.run_button.setEnabled(bool(remaining))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'rows_host'):
            # 等布局把 viewport 的新尺寸应用完再判断，避免用到旧宽度
            QTimer.singleShot(0, self._reflow_if_needed)

    def _reflow_if_needed(self):
        if not hasattr(self, 'rows_host') or not self._tiles:
            return
        columns = self._layout_columns(len(self._tiles))
        if self._columns_cache is None or columns != self._columns_cache:
            self.refresh()

    # ------------------------------------------------------------------ 跳转
    def _settings_tab(self):
        window = self.window()
        stacked = getattr(window, 'stackedWidget', None)
        if stacked is None:
            return None
        for widget in stacked.findChildren(QWidget):
            if type(widget).__name__ == 'TaskSettingsTab':
                return widget
        return None

    def _open_task(self, task):
        """点击首页卡片：切到任务设定页，并选中这个任务。"""
        target = self._settings_tab()
        if target is None or task is None:
            return
        try:
            target.refresh()
            target.select_task(task)
        except Exception as error:  # noqa: BLE001 - 跳转失败不影响首页
            print(f'open task failed: {error}')
            return
        window = self.window()
        if hasattr(window, 'switchTo'):
            window.switchTo(target)

    # ------------------------------------------------------------------ 一键日常
    def _run_daily(self):
        if self._run_thread is not None:
            return
        remaining = daily_state.remaining_tasks(visible_tasks())
        if not remaining:
            return
        self._run_thread = DailyRunThread(remaining)
        self._run_thread.progress.connect(self._on_progress)
        self._run_thread.failed.connect(self._on_failed)
        self._run_thread.finished.connect(self._on_run_finished)
        self.run_button.setEnabled(False)
        self._run_thread.start()

    def _on_progress(self, task_name, index, total):
        self.run_button.setText(self.tr('正在执行 {}/{}').format(index, total))
        self.summary_hint.setText(task_name)

    def _on_failed(self, message):
        self.summary_hint.setText(message)

    def _on_run_finished(self):
        self._run_thread = None
        self.run_button.setText(self.tr('一键完成日常'))
        self.run_button.setEnabled(True)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def _promote_navigation(self):
        """把首页、任务设定排到「截图方式」之前，让首页成为左侧列表第一项。

        主窗口构造时先加「截图方式」再加 custom_tabs，因此只能等窗口就绪后重排一次。
        """
        if getattr(self, '_nav_promoted', False):
            return
        window = self.window()
        nav = getattr(window, 'navigationInterface', None)
        if nav is None or nav.widget(self.objectName()) is None:
            # 窗口还没就绪，稍后再试
            QTimer.singleShot(300, self._promote_navigation)
            return
        self._nav_promoted = True
        tabs = [self]
        for widget in window.stackedWidget.findChildren(QWidget):
            if type(widget).__name__ == 'TaskSettingsTab':
                tabs.append(widget)
                break
        for index, tab in enumerate(tabs):
            route = tab.objectName()
            if nav.widget(route) is None:
                continue
            try:
                nav.removeWidget(route)
                nav.insertItem(index, route, tab.icon, window.app.tr(tab.name),
                               onClick=lambda *_args, _tab=tab: window.switchTo(_tab),
                               position=NavigationItemPosition.SCROLL)
            except Exception as error:  # noqa: BLE001 - 排序失败不影响功能
                print(f'nav reorder skipped: {error}')
                return
        window.switchTo(self)
        # 标题栏只显示应用名，去掉后面的版本号与 profile 后缀
        title = (og.config or {}).get('gui_title')
        if title:
            window.setWindowTitle(title)
