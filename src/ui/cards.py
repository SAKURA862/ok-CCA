"""首页 / 任务设定页共用的圆角卡片、环形进度与图标控件。

卡片风格参考 YES-BD2：无描边、白色背景，四周一层很薄的主题色阴影。
阴影是卡片自己画在内部留白里的（不依赖 QGraphicsDropShadowEffect），
因此不会被父控件裁掉，也不会在四角露出小三角。
"""

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QSizePolicy, QVBoxLayout, QWidget

from qfluentwidgets import FluentIcon, IconWidget, isDarkTheme, qconfig, themeColor

from ok.ui.qt.common.icons import resolve_icon
from src.ui import theme

CARD_RADIUS = 12
SHADOW_PAD = 8          # 卡片四周留给阴影的空白
PAGE_PADDING = 40       # 页面内容距离窗口左右边缘的距离
SHADOW_OFFSET = 3       # 阴影整体向下偏移，避免顶部出现一圈描边感


def card_bg() -> QColor:
    return theme.color('card_bg')


def card_hover() -> QColor:
    return theme.color('hover_bg')


def shadow_color() -> QColor:
    """阴影跟随主题色：很薄的一层，深色主题下稍浓。"""
    color = QColor(theme.palette().shadow or themeColor().name())
    color.setAlpha(96 if isDarkTheme() else 60)
    return color


def blend(a: QColor, b: QColor, ratio: float) -> QColor:
    """按比例把颜色 a 混向 b（ratio 0~1），用于悬停过渡。"""
    ratio = max(0.0, min(1.0, ratio))
    return QColor(
        int(a.red() + (b.red() - a.red()) * ratio),
        int(a.green() + (b.green() - a.green()) * ratio),
        int(a.blue() + (b.blue() - a.blue()) * ratio),
        int(a.alpha() + (b.alpha() - a.alpha()) * ratio),
    )


class RoundedCard(QFrame):
    """统一圆角卡片：内部留白里画一层薄阴影，再填充圆角背景。

    ``bg_color`` / ``border_color`` / ``hover_color`` 可以在子类里改，
    paintEvent 会优先使用它们。
    """

    def __init__(self, parent=None, radius: int = CARD_RADIUS, hoverable: bool = False,
                 shadow: bool = True):
        super().__init__(parent)
        self._radius = radius
        self._hoverable = hoverable
        self._shadow = shadow
        self._pad = SHADOW_PAD if shadow else 0
        self.bg_color = None
        self.hover_color = None
        self.border_color = None
        self._hovered = False
        self._hover_ratio = 0.0
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(140)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_anim)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        qconfig.themeChanged.connect(self.update)
        theme.signals.changed.connect(self.update)

    # ------------------------------------------------------------------ 绘制
    @property
    def pad(self) -> int:
        return self._pad

    def card_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(self._pad, self._pad, -self._pad, -self._pad)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.card_rect()

        if self._shadow:
            self._paint_shadow(painter, rect)

        painter.setPen(Qt.NoPen)
        background = self.bg_color if self.bg_color is not None else card_bg()
        if self._hoverable and self._hover_ratio > 0:
            hover = self.hover_color if self.hover_color is not None else card_hover()
            background = blend(background, hover, self._hover_ratio)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, self._radius, self._radius)

        if self.border_color is not None:
            pen = QPen(self.border_color, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            inner = rect.adjusted(1, 1, -1, -1)
            painter.drawRoundedRect(inner, self._radius - 1, self._radius - 1)
        painter.end()

    def _paint_shadow(self, painter: QPainter, rect: QRectF):
        """三层沿向下的柔光，贴着卡片底部散开，看起来是「薄阴影」而不是描边。"""
        base = shadow_color()
        factors = (0.37, 0.19, 0.07)
        expands = (2.0, 4.0, 6.0)
        painter.setPen(Qt.NoPen)
        for factor, expand in zip(factors, expands):
            alpha = int(base.alpha() * factor)
            if alpha <= 0:
                continue
            color = QColor(base)
            color.setAlpha(alpha)
            painter.setBrush(color)
            path = QPainterPath()
            path.addRoundedRect(
                rect.adjusted(-expand, -expand + SHADOW_OFFSET, expand, expand + SHADOW_OFFSET),
                self._radius + expand,
                self._radius + expand,
            )
            painter.drawPath(path)

    # ------------------------------------------------------------------ 悬停
    def _animate_hover(self, target: float):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_ratio)
        self._hover_anim.setEndValue(float(target))
        self._hover_anim.start()

    def _on_hover_anim(self, value):
        self._hover_ratio = float(value)
        self.update()

    def enterEvent(self, event):
        if self._hoverable:
            self._hovered = True
            self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._hoverable:
            self._hovered = False
            self._animate_hover(0.0)
        super().leaveEvent(event)


class RingProgress(QWidget):
    """今日日常完成度的环形进度（中心显示 已完成 / 总数），颜色跟随主题色。"""

    def __init__(self, parent=None, size: int = 92, thickness: int = 9):
        super().__init__(parent)
        self._done = 0
        self._total = 0
        self._thickness = thickness
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_value(self, done: int, total: int):
        done = max(0, int(done))
        total = max(0, int(total))
        if done > total:
            done = total
        if (done, total) == (self._done, self._total):
            return
        self._done, self._total = done, total
        self.update()

    def _text_colors(self):
        if isDarkTheme():
            return QColor('#E8E8EE'), QColor(theme.palette().subtext)
        return QColor(theme.palette().text), QColor(theme.palette().subtext)

    def paintEvent(self, _event):
        accent = theme.color('accent')
        track = QColor(accent)
        track.setAlpha(48 if not isDarkTheme() else 70)
        text_color, muted = self._text_colors()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        inset = self._thickness / 2 + 1
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)

        pen = QPen(track, self._thickness)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)

        if self._total:
            ratio = self._done / self._total
            pen.setColor(accent)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, -int(ratio * 360 * 16))

        big = QFont(self.font())
        big.setPointSize(22)
        big.setBold(True)
        small = QFont(self.font())
        small.setPointSize(10)
        small.setBold(True)

        big_metrics = QFontMetrics(big)
        small_metrics = QFontMetrics(small)
        left_text = str(self._done)
        right_text = f'/{self._total}'
        left_width = big_metrics.horizontalAdvance(left_text)
        right_width = small_metrics.horizontalAdvance(right_text)
        gap = 2
        total_width = left_width + gap + right_width
        center = self.rect().center()
        left_x = center.x() - total_width / 2
        baseline = center.y() + (big_metrics.ascent() - big_metrics.descent()) / 2

        painter.setFont(big)
        painter.setPen(text_color)
        painter.drawText(int(left_x), int(baseline), left_text)
        painter.setFont(small)
        painter.setPen(muted)
        painter.drawText(int(left_x + left_width + gap), int(baseline), right_text)
        painter.end()


def task_icon(task, size: int = 36, parent=None) -> IconWidget:
    """任务图标控件；任务没有可用图标时用 PLAY 占位。

    注意：不能继承 IconWidget 再重写 __init__，qfluentwidgets 的
    singledispatchmethod 会在内部调用 self.__init__(parent) 造成无限递归。
    """
    icon = resolve_icon(getattr(task, 'icon', None), fallback=FluentIcon.PLAY)
    if not isinstance(icon, FluentIcon):
        icon = FluentIcon.PLAY
    widget = IconWidget(icon, parent)
    widget.setFixedSize(size, size)
    return widget


def title_font(size: int = 16, bold: bool = True) -> QFont:
    font = QFont()
    font.setPointSize(size)
    font.setBold(bold)
    return font


def muted_color() -> QColor:
    return theme.color('subtext')


def divider_color() -> QColor:
    return QColor(theme.palette().subtext).lighter(175) if not isDarkTheme() else QColor('#3A3A42')


def make_vertical(widget, margins=(0, 0, 0, 0), spacing: int = 6) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout
