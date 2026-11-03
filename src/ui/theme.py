"""主题系统。

设计目标：
- 内置「浅色 / 深色 / 跟随系统」仍由 qfluentwidgets 负责，保持原有行为；
- 新增的配色主题是纯数据（`Palette`），每个部位一个字段，方便以后做「用户自定义各部分颜色」；
- 自定义主题只做两件事：切换主色（qfluentwidgets 的 themeColor）+ 在窗口上挂一层 QSS 覆盖。
  所有自定义组件都通过 `palette()` 取色，不写死颜色。

新增一套主题只需要在 `CUSTOM_THEMES` 里追加一个 `Palette`。
"""

from dataclasses import asdict, dataclass, fields, replace

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from qfluentwidgets import Theme, isDarkTheme, qconfig, setTheme, themeColor

from ok import Config, Logger

logger = Logger.get_logger(__name__)

# 主题选择 + 各主题各区域颜色都存这里，方便来回切换与后续自定义
STATE = Config('UiTheme', {'selected': 'light', 'themes': {}})


@dataclass(frozen=True)
class Palette:
    """一套界面配色。

    字段就是「部位」，以后做自定义时，用户改的也是这些字段。
    """

    key: str
    label: str
    mode: str  # 'custom' 走覆盖层；'light' / 'dark' / 'auto' 交给 qfluentwidgets
    sidebar_bg: str
    titlebar_bg: str
    page_bg: str
    card_bg: str
    hover_bg: str
    selected_bg: str
    accent: str
    text: str
    subtext: str
    border: str
    shadow: str


# 默认（跟着浅色/深色走的）配色，给自定义组件兜底
_LIGHT_DEFAULTS = Palette(
    key='light', label='浅色', mode='light',
    sidebar_bg='#F3F3F3', titlebar_bg='#F3F3F3', page_bg='#F3F3F3',
    card_bg='#FFFFFF', hover_bg='#F4F2F1', selected_bg='#E8E2DF',
    accent='#74584D', text='#1B1B1F', subtext='#6B6B75',
    border='#00000000', shadow='#74584D',
)

_DARK_DEFAULTS = replace(
    _LIGHT_DEFAULTS, key='dark', label='深色', mode='dark',
    sidebar_bg='#1C1C1E', titlebar_bg='#1C1C1E', page_bg='#1C1C1E',
    card_bg='#27272B', hover_bg='#33333A', selected_bg='#3B3540',
    accent='#C9A48F', text='#F2F2F5', subtext='#A8A8B3',
)

# 自定义配色主题：追加新主题就加一个 Palette
CUSTOM_THEMES = [
    Palette(
        key='katina_lianyu',
        label='卡提那·联域',
        mode='custom',
        sidebar_bg='#FFF0F6',
        titlebar_bg='#FFF0F6',
        page_bg='#FFF9FC',
        card_bg='#FFFFFF',
        hover_bg='#FFF0F6',
        selected_bg='#F9DCE9',
        accent='#EFA1C0',
        text='#3A2B32',
        subtext='#9A8590',
        border='#00000000',
        shadow='#EFA1C0',
    ),
]

# 内置主题：永远排在所有自定义主题之后
BUILTIN_THEMES = [
    Palette(key='light', label='浅色', mode='light',
            sidebar_bg='', titlebar_bg='', page_bg='', card_bg='', hover_bg='',
            selected_bg='', accent='', text='', subtext='', border='', shadow=''),
    Palette(key='dark', label='深色', mode='dark',
            sidebar_bg='', titlebar_bg='', page_bg='', card_bg='', hover_bg='',
            selected_bg='', accent='', text='', subtext='', border='', shadow=''),
    Palette(key='auto', label='跟随系统', mode='auto',
            sidebar_bg='', titlebar_bg='', page_bg='', card_bg='', hover_bg='',
            selected_bg='', accent='', text='', subtext='', border='', shadow=''),
]

_REGISTRY = {theme.key: theme for theme in CUSTOM_THEMES}
_BUILTIN_MODE = {
    'light': Theme.LIGHT,
    'dark': Theme.DARK,
    'auto': Theme.AUTO,
}

# 可以按主题单独存储/修改的「部位」（字段名即配置项名字）
COLOR_FIELDS = tuple(
    f.name for f in fields(Palette)
    if f.name not in ('key', 'label', 'mode')
)


class ThemeSignals(QObject):
    """主题切换后通知所有自定义组件重绘。"""

    changed = Signal()


signals = ThemeSignals()

_window = None


# --------------------------------------------------------------------- 查询
def all_themes():
    """设置页展示顺序：自定义主题在前，浅色/深色/跟随系统在最后。"""
    return [_resolve_custom(t) for t in CUSTOM_THEMES] + list(BUILTIN_THEMES)


def _builtin_base(key: str) -> Palette:
    """某套内置主题的「原始」配色（未叠加用户改过的颜色）。"""
    mode = _BUILTIN_MODE.get(key, Theme.LIGHT)
    if mode == Theme.DARK:
        base = _DARK_DEFAULTS
    elif mode == Theme.LIGHT:
        base = _LIGHT_DEFAULTS
    else:  # 跟随系统：按当前系统深浅色取底
        base = _DARK_DEFAULTS if isDarkTheme() else _LIGHT_DEFAULTS
    accent = QColor(themeColor()).name()
    return replace(base, key=key, accent=accent, shadow=accent)


def _saved_colors(key: str) -> dict:
    themes = STATE.get('themes') or {}
    saved = themes.get(key) or {}
    return {k: v for k, v in saved.items() if k in COLOR_FIELDS and v}


def _resolve_any(base: Palette) -> Palette:
    """把 configs/UiTheme.json 里存过的颜色合并进主题定义（自定义和内置都支持）。"""
    saved = _saved_colors(base.key)
    return replace(base, **saved) if saved else base


def _resolve_custom(base: Palette) -> Palette:
    return _resolve_any(base)


def _store_snapshot(key: str, colors: dict | None = None):
    """把某套主题各部位的颜色存进 configs/UiTheme.json，方便来回切换与手工微调。"""
    themes = dict(STATE.get('themes') or {})
    if colors is None:
        colors = theme_colors(key)
    if not colors:
        return
    current = dict(themes.get(key) or {})
    for k, v in colors.items():
        current.setdefault(k, v)
    themes[key] = current
    STATE['themes'] = themes


def save_colors(key: str, **colors):
    """修改某个主题的若干部位颜色并持久化（给后续「自定义颜色」界面用）。"""
    if key not in _REGISTRY and key not in _BUILTIN_MODE:
        return None
    clean = {k: str(v) for k, v in colors.items() if k in COLOR_FIELDS and v}
    themes = dict(STATE.get('themes') or {})
    merged = dict(themes.get(key) or {})
    merged.update(clean)
    themes[key] = merged
    STATE['themes'] = themes
    p = palette()
    if key == selected_key() and _window is not None:
        if key in _REGISTRY:
            _customize_window(_window, p)
        else:
            _customize_window(_window, p)
        signals.changed.emit()
    return p


def theme_colors(key: str) -> dict:
    """导出某个主题的全部部位颜色，便于保存/还原。"""
    if key in _REGISTRY:
        p = _resolve_any(_REGISTRY[key])
    elif key in _BUILTIN_MODE:
        p = _resolve_any(_builtin_base(key))
    else:
        return {}
    data = asdict(p)
    return {k: data[k] for k in COLOR_FIELDS}


def selected_key() -> str:
    return STATE.get('selected') or 'light'


def is_custom(key: str | None = None) -> bool:
    return (key or selected_key()) in _REGISTRY


def _builtin_palette() -> Palette:
    """内置主题：完全跟随 ok-script / qfluentwidgets 自己的取色，保持原样。

    主色取 `themeColor()`，所以环形进度、开关、按钮颜色天然一致。
    """
    dark = isDarkTheme()
    accent = QColor(themeColor()).name()
    base = _DARK_DEFAULTS if dark else _LIGHT_DEFAULTS
    return replace(base, accent=accent, shadow=accent)


def palette() -> Palette:
    """当前生效的配色，自定义组件统一从这里取色。"""
    key = selected_key()
    if key in _REGISTRY:
        return _resolve_any(_REGISTRY[key])
    return _resolve_any(_builtin_base(key))


def color(role: str) -> QColor:
    return QColor(getattr(palette(), role))


# --------------------------------------------------------------------- 应用
def _overlay_qss(p: Palette) -> str:
    return f"""
    NavigationPanel {{ background-color: {p.sidebar_bg}; }}
    #appTitleBar {{ background-color: {p.titlebar_bg}; }}
    """


def apply(key: str, save: bool = True):
    """切换主题，并立刻作用到已存在的窗口上。"""
    global _window
    if key not in _REGISTRY and key not in _BUILTIN_MODE:
        key = 'light'
    if save:
        STATE['selected'] = key

    if key in _REGISTRY:
        p = _resolve_custom(_REGISTRY[key])
        _store_snapshot(key)
        qconfig.set(qconfig.themeMode, Theme.LIGHT, save=False)
        qconfig.set(qconfig.themeColor, QColor(p.accent), save=False)
        setTheme(Theme.LIGHT)
        if _window is not None:
            _customize_window(_window, p)
    else:
        mode = _BUILTIN_MODE[key]
        qconfig.set(qconfig.themeMode, mode, save=True)
        setTheme(mode)
        base = _builtin_base(key)
        merged = _resolve_any(base)
        _store_snapshot(key, asdict(base))
        if _window is not None:
            if merged != base:  # 用户在配置里改过内置主题的部分颜色
                _customize_window(_window, merged)
            else:
                _restore_window(_window)
                _settle_window(_window)

    signals.changed.emit()
    logger.info(f'theme applied: {key}')


def _customize_window(window, p: Palette):
    window.setMicaEffectEnabled(False)
    try:
        window.navigationInterface.setAcrylicEnabled(False)
    except Exception:  # noqa: BLE001 - 老版本没有该 API
        pass
    window.setCustomBackgroundColor(QColor(p.page_bg), QColor(p.page_bg))
    window.setStyleSheet(_overlay_qss(p))
    # ok-script 在 themeChanged 时会把主色同步回 _configured_theme_color，这里跟着改
    try:
        original = getattr(window, '_theme_orig_accent', None)
        if original is None:
            original = getattr(window, '_configured_theme_color', None)
            window._theme_orig_accent = QColor(original) if original is not None else None
        window._configured_theme_color = QColor(p.accent)
    except Exception:  # noqa: BLE001
        pass
    # 标题栏本身是透明 QWidget，需要单独铺底色
    title_bar = getattr(window, 'titleBar', None)
    if title_bar is not None:
        from PySide6.QtCore import Qt

        title_bar.setObjectName('appTitleBar')
        title_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        title_bar.style().unpolish(title_bar)
        title_bar.style().polish(title_bar)


def _settle_window(window, tries: int = 10):
    """等 qfluentwidgets 真正切换完深浅色后，再铺一次背景。

    `qconfig.set(themeMode, ...)` 应用到控件上是异步的，紧接着调用
    `_restore_window()` 时 `isDarkTheme()` 可能还是旧值，背景就会漏成上一个主题的底色。
    这里用定时轮询把背景色校准到当前主题。
    """
    from PySide6.QtCore import QTimer

    def tick(remaining: int):
        if window is None:
            return
        _restore_window(window)
        expected = QColor('#202020') if isDarkTheme() else QColor('#F3F3F3')
        if remaining > 0 and window.backgroundColor != expected:
            QTimer.singleShot(120, lambda: tick(remaining - 1))

    QTimer.singleShot(60, lambda: tick(tries))


def _restore_window(window):
    from PySide6.QtCore import Qt
    from qfluentwidgets import isDarkTheme

    window.setStyleSheet('')
    title_bar = getattr(window, 'titleBar', None)
    if title_bar is not None:
        title_bar.setStyleSheet('')
        title_bar.setObjectName('')
        title_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        title_bar.style().unpolish(title_bar)
        title_bar.style().polish(title_bar)
    # 内置主题也用实色背景：Mica 的透明底跟随系统浅色，会让深色主题「漏白」
    window.setMicaEffectEnabled(False)
    try:
        window.navigationInterface.setAcrylicEnabled(False)
    except Exception:  # noqa: BLE001
        pass
    # 主色回到 ok-script 自己记录的配置色
    configured = getattr(window, '_theme_orig_accent', None)
    if configured is None:
        configured = getattr(window, '_configured_theme_color', None)
    if configured is not None:
        try:
            qconfig.set(qconfig.themeColor, QColor(configured), save=False)
            window._configured_theme_color = QColor(configured)
        except Exception:  # noqa: BLE001
            pass
    light_bg, dark_bg = QColor('#F3F3F3'), QColor('#202020')
    window.setCustomBackgroundColor(light_bg, dark_bg)
    try:
        window._updateStackedBackground()
    except Exception:  # noqa: BLE001
        pass
    logger.info(
        f'restore window: dark={isDarkTheme()} mode={qconfig.themeMode.value} '
        f'acc={qconfig.get(qconfig.themeColor).name()} bg={window.backgroundColor.name()}'
    )
    window.update()


def attach(window):
    """记录主窗口，并按已保存的选择应用一次主题。"""
    global _window
    _window = window
    apply(selected_key(), save=False)


# --------------------------------------------------------------------- 安装
def install():
    """启动时调用：接管设置页的主题选项。"""
    try:
        from src.ui.theme_settings import patch_settings_tab

        patch_settings_tab()
    except Exception:  # noqa: BLE001 - 任何异常都不该拦住程序启动
        logger.exception('install theme settings failed')

    # 系统主题/强调色变化后，自定义配色要重新盖一次
    qconfig.themeChangedFinished.connect(_reapply_if_custom)


def _reapply_if_custom(*_args):
    if _window is None:
        return
    if is_custom():
        p = _resolve_custom(_REGISTRY[selected_key()])
        qconfig.set(qconfig.themeColor, QColor(p.accent), save=False)
        _customize_window(_window, p)
    else:
        # 内置主题：主题切换完成后重新铺一次默认外观（实色背景 + 主色还原）
        _restore_window(_window)
        _settle_window(_window)
