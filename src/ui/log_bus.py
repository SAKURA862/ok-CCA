"""进程内日志总线：把 ok-script 的 logging 记录变成界面可订阅的事件流。

设计要点：
- ok-script 的所有日志都汇到标准库的 ``logging.getLogger("ok")``（见 ok/util/logger.py），
  所以这里只挂一个 ``logging.Handler`` 就能拿到全量日志，不需要改 ok-script。
- logging 可能来自任意线程，处理器只把记录塞进环形缓冲并置脏位；
  真正通知界面的是 GUI 线程里的 QTimer，每 ``FLUSH_MS`` 合并发一次信号，避免高频日志打爆重绘。
- ``LogView`` 是页面与底边栏共用的只读视图，自己订阅总线、自己维护「吸底」与级别过滤。
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import QFrame, QPlainTextEdit

from ok import Config

from src.ui import theme
from src.ui.cards import divider_color

# 级别：页面上的下拉框按这个顺序展示
LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR')
LEVEL_NO = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING, 'ERROR': logging.ERROR}

# 合并刷新间隔（毫秒）与各视图默认保留行数
FLUSH_MS = 100
PAGE_MAX_LINES = 2000
DOCK_MAX_LINES = 500

# 界面设置：底边栏是否启用、默认级别、页面保留行数
SETTINGS = Config('UiLog', {'dock_enabled': False, 'level': 'INFO', 'max_lines': PAGE_MAX_LINES})


class _SettingsSignals(QObject):
    """设置变化通知（页面写配置、底边栏跟着显示/隐藏）。"""

    changed = Signal()


settings_changed = _SettingsSignals()


def _level_color(levelno: int) -> QColor:
    """按级别取颜色；正常日志用主题正文色，警告/错误用固定状态色（深浅主题都够对比）。"""
    if levelno >= logging.ERROR:
        return QColor('#D9534F')
    if levelno >= logging.WARNING:
        return QColor('#C8871F')
    if levelno <= logging.DEBUG:
        return QColor(theme.palette().subtext)
    return QColor(theme.palette().text)


@dataclass(frozen=True)
class LogEntry:
    seq: int
    when: str
    levelno: int
    level: str
    source: str
    message: str


class _BusHandler(logging.Handler):
    """把 logging 记录转交给总线；任何异常都不能影响业务日志。"""

    def __init__(self, bus: 'LogBus'):
        super().__init__(logging.DEBUG)
        self._bus = bus

    def emit(self, record):
        try:
            self._bus.append(record)
        except Exception:  # noqa: BLE001 - 日志显示失败不应该拖垮程序
            self.handleError(record)


class LogBus(QObject):
    """日志环形缓冲 + 批量通知。"""

    batch_ready = Signal()

    def __init__(self, max_lines: int = PAGE_MAX_LINES):
        super().__init__()
        self._lock = threading.Lock()
        self._entries = deque(maxlen=max(1, int(max_lines)))
        self._seq = 0
        self._dirty = False
        self._timer = None
        self._handler = None

    # ------------------------------------------------------------------ 安装
    def install(self):
        """挂到 ok 的 logger 上，并（在 GUI 线程里）启动合并刷新定时器。"""
        if self._handler is not None:
            return self
        handler = _BusHandler(self)
        logging.getLogger('ok').addHandler(handler)
        self._handler = handler
        try:
            self._start_timer()
        except Exception:  # noqa: BLE001 - 没有 QApplication 时退化为同步通知
            self._timer = None
        return self

    def _start_timer(self):
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            return
        timer = QTimer(self)
        timer.setInterval(FLUSH_MS)
        timer.timeout.connect(self._flush)
        timer.start()
        self._timer = timer

    # ------------------------------------------------------------------ 写入
    def append(self, record: logging.LogRecord):
        message = record.getMessage()
        if record.exc_info:
            message = f'{message}\n{logging.Formatter().formatException(record.exc_info)}'
        when = time.strftime('%H:%M:%S', time.localtime(record.created))
        with self._lock:
            self._seq += 1
            self._entries.append(
                LogEntry(self._seq, when, record.levelno, record.levelname,
                         record.name.split('.')[-1], message)
            )
            self._dirty = True
        if self._timer is None:
            # 没有 Qt 事件循环时直接通知（headless 下没有订阅者，等于空转）
            self._flush()

    def _flush(self):
        with self._lock:
            if not self._dirty:
                return
            self._dirty = False
        self.batch_ready.emit()

    # ------------------------------------------------------------------ 读取
    def since(self, seq: int) -> list[LogEntry]:
        with self._lock:
            return [entry for entry in self._entries if entry.seq > seq]

    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def clear(self):
        with self._lock:
            self._entries.clear()
        self.batch_ready.emit()

    def text(self) -> str:
        with self._lock:
            entries = list(self._entries)
        return '\n'.join(f'[{e.when}] {e.level:<7} {e.source}: {e.message}' for e in entries)


class LogView(QPlainTextEdit):
    """只读日志视图：按级别着色、自动吸底、订阅总线增量刷新。"""

    def __init__(self, parent=None, max_lines: int = PAGE_MAX_LINES, compact: bool = False):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setMaximumBlockCount(int(max_lines))
        self.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        font = QFont('Consolas')
        font.setPointSize(9 if compact else 10)
        self.setFont(font)

        self._compact = compact
        self._min_level = LEVEL_NO.get(str(SETTINGS.get('level') or 'INFO').upper(), logging.INFO)
        self._last_seq = 0
        self._stick = True
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

        bus.batch_ready.connect(self._on_batch)
        theme.signals.changed.connect(self._on_theme_changed)
        self._apply_style()
        self.reload()

    # ------------------------------------------------------------------ 外观
    def _on_theme_changed(self):
        """主题切换后颜色要重算：文字色是写进每个字符格式里的，必须整屏重绘。"""
        self._apply_style()
        self.reload()

    def _apply_style(self):
        palette = theme.palette()
        self.setStyleSheet(
            'QPlainTextEdit {'
            f' background-color: {palette.card_bg};'
            f' color: {palette.text};'
            f' border: 1px solid {divider_color().name()};'
            ' border-radius: 10px;'
            f' padding: {4 if self._compact else 10}px;'
            '}'
        )

    # ------------------------------------------------------------------ 数据
    def set_level(self, level: str):
        """切换级别过滤：重建视图内容，只显示 >= 该级别的日志。"""
        self._min_level = LEVEL_NO.get(str(level).upper(), logging.INFO)
        self.reload()

    def block_append(self, blocked: bool):
        """暂停/恢复刷新：暂停期间新日志仍进总线，恢复时一次性补上。"""
        self._blocked = bool(blocked)
        if not blocked:
            self._append_entries(bus.since(self._last_seq))

    def reload(self):
        self.clear()
        self._last_seq = 0
        self._append_entries(bus.since(0))

    def _on_batch(self):
        self._append_entries(bus.since(self._last_seq))

    def _append_entries(self, entries):
        if not entries or getattr(self, '_blocked', False):
            return
        bar = self.verticalScrollBar()
        at_bottom = self._stick or bar.value() >= bar.maximum() - 4
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setUpdatesEnabled(False)
        try:
            for entry in entries:
                self._last_seq = max(self._last_seq, entry.seq)
                if entry.levelno < self._min_level:
                    continue
                cursor.insertText(self._line_of(entry), self._format_of(entry))
                cursor.insertText('\n', self._format_of(entry))
        finally:
            self.setUpdatesEnabled(True)
        if at_bottom:
            self._scroll_to_end()

    @staticmethod
    def _line_of(entry: LogEntry) -> str:
        source = f' {entry.source}:' if entry.source else ''
        message = entry.message.replace('\r', '')
        return f'{entry.when} {entry.level:<7}{source} {message}'

    @staticmethod
    def _format_of(entry: LogEntry) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(_level_color(entry.levelno))
        return fmt

    # ------------------------------------------------------------------ 滚动
    def _scroll_to_end(self):
        self._stick = True
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_scroll_changed(self, value):
        bar = self.verticalScrollBar()
        self._stick = value >= bar.maximum() - 4


bus = LogBus()
