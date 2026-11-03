"""设置页里的「应用主题」卡片：展开后是一排主题卡片。

内置的 浅色 / 深色 / 跟随系统 永远排在最后；自定义配色在前。
新增主题只需要在 `src/ui/theme.py` 的 `CUSTOM_THEMES` 里加一项，这里会自动出现。
"""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QGridLayout, QWidget

from qfluentwidgets import ExpandGroupSettingCard, FluentIcon, isDarkTheme

from src.ui import theme

CHIP_WIDTH = 208
CHIP_HEIGHT = 76
CHIP_GAP = 12
COLUMNS = 3


class ThemeChip(QAbstractButton):
    """一张主题卡片：名字 + 四个部位的色块预览。"""

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(CHIP_WIDTH, CHIP_HEIGHT)
        self.setToolTip(item.label)
        self.clicked.connect(lambda: theme.apply(item.key))
        theme.signals.changed.connect(self._sync)

    def _sync(self):
        self.setChecked(theme.selected_key() == self.item.key)
        self.update()

    def sizeHint(self):
        return QSize(CHIP_WIDTH, CHIP_HEIGHT)

    def _colors(self):
        """返回 (侧边栏, 内容底, 选中, 主色)。"""
        if theme.is_custom(self.item.key):
            p = theme._REGISTRY[self.item.key]
            return p.sidebar_bg, p.page_bg, p.selected_bg, p.accent
        if self.item.mode == 'dark':
            return '#1C1C1E', '#1C1C1E', '#3B3540', '#C9A48F'
        if self.item.mode == 'auto':
            return '#F3F3F3', '#202020', '#D9D2CE', '#74584D'
        return '#F3F3F3', '#FFFFFF', '#E8E2DF', '#74584D'

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        p = theme.palette()
        selected = self.isChecked()
        radius = 10
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        # 卡片背景：自定义主题用当前主题的卡片色，内置主题跟随明暗
        if selected:
            bg = QColor(theme.color('accent'))
            bg.setAlpha(28 if not isDarkTheme() else 60)
        else:
            bg = QColor(theme.color('card_bg'))
        painter.fillPath(path, bg)

        border = QColor(p.accent) if selected else QColor(0, 0, 0, 26 if not isDarkTheme() else 60)
        pen = QPen(border)
        pen.setWidthF(2.0 if selected else 1.0)
        painter.setPen(pen)
        painter.drawPath(path)

        # 名字
        font = QFont(self.font())
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(p.text))
        name_rect = rect.adjusted(14, 10, -14, -42)
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, self.item.label)

        # 色块预览
        colors = self._colors()
        swatch_w = (CHIP_WIDTH - 28 - 3 * 6) / 4
        x = rect.left() + 14
        y = rect.bottom() - 26
        for color in colors:
            swatch = QRectF(x, y, swatch_w, 14)
            swatch_path = QPainterPath()
            swatch_path.addRoundedRect(swatch, 4, 4)
            painter.fillPath(swatch_path, QColor(color))
            x += swatch_w + 6

        painter.end()


class ThemeSelectorCard(ExpandGroupSettingCard):
    """设置页顶部的主题选择卡片。"""

    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.BRUSH,
            self.tr('应用主题'),
            self.tr('选择界面配色方案，自定义配色排在前面'),
            parent,
        )
        panel = QWidget(self)
        grid = QGridLayout(panel)
        grid.setContentsMargins(48, 16, 48, 20)
        grid.setHorizontalSpacing(CHIP_GAP)
        grid.setVerticalSpacing(CHIP_GAP)

        self.chips = []
        for index, item in enumerate(theme.all_themes()):
            chip = ThemeChip(item, panel)
            row, column = divmod(index, COLUMNS)
            grid.addWidget(chip, row, column, Qt.AlignLeft)
            self.chips.append(chip)
            if item.key == theme.selected_key():
                chip.setChecked(True)

        for column in range(COLUMNS):
            grid.setColumnStretch(column, 0)
        grid.setColumnStretch(COLUMNS, 1)

        self.addGroupWidget(panel)
        theme.signals.changed.connect(self._sync_all)
        self.setExpand(True)

    def _sync_all(self):
        for chip in self.chips:
            chip._sync()  # noqa: SLF001 - 同一个模块内的兄弟控件


def patch_settings_tab():
    """把 ok-script 设置页内置的「应用主题」下拉替换成本卡片。"""
    from ok.ui.qt.settings.SettingTab import SettingTab

    if getattr(SettingTab, '_okcca_theme_patched', False):
        return

    method_name = '_SettingTab__initLayout'
    original = getattr(SettingTab, method_name)

    def __initLayout(self):
        original(self)
        try:
            card = getattr(self, 'themeCard', None)
            group = getattr(self, 'basic_group', None)
            if card is not None and group is not None:
                # 只从布局里摘掉并隐藏，保留对象：SettingTab 后面还会连它的信号
                group.vBoxLayout.removeWidget(card)
                card.hide()
        except Exception:  # noqa: BLE001 - 替换失败就保留原卡片
            pass
        try:
            self.themeSelector = ThemeSelectorCard(parent=self.basic_group)
            self.basic_group.vBoxLayout.insertWidget(0, self.themeSelector)
        except Exception:  # noqa: BLE001
            pass

    setattr(SettingTab, method_name, __initLayout)
    SettingTab._okcca_theme_patched = True
