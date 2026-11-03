"""主窗口的界面裁剪：只隐藏，不删除。

- 语言下拉只保留「简体中文」，其它语言项仍然存在于配置与代码里，
  只是在下拉列表里隐藏，后续要支持更多语言时把这里的隐藏列表去掉即可。
- 左侧导航隐藏 ok-script 自带的「任务」「模板」两页；页面对象、路由都还在，
  只是不在侧边栏显示，需要时仍然可以 switchTo 过去。
"""

from PySide6.QtCore import QTimer

from ok import Logger

logger = Logger.get_logger(__name__)

# 语言下拉里保留下标（SettingTab 的 texts 顺序：简体中文、繁體中文、English、
# Español、日本語、한국인、Use system setting）
LANGUAGE_VISIBLE_INDEX = 0

# 侧边栏需要隐藏的页面属性名
HIDDEN_NAV_PAGES = ('onetime_tab', 'template_tab')


def _restrict_language(setting_tab):
    """只在下拉里显示「简体中文」，其它项移到 _hidden_items 里留着。

    qfluentwidgets 的 ComboBox 每次展开都用 ``combo.items`` 重新生成菜单，
    所以把多余项从 items 里摘出来就等于隐藏；原对象仍挂在 ``_hidden_items`` 上，
    以后要放开多语言时把它塞回 items 即可。
    """
    card = getattr(setting_tab, 'languageCard', None)
    combo = getattr(card, 'comboBox', None)
    items = getattr(combo, 'items', None)
    if not items or len(items) <= 1:
        return
    # 先把当前选中项切到「简体中文」，只改显示不改配置，避免触发重启提示
    if combo.currentIndex() != LANGUAGE_VISIBLE_INDEX:
        combo.blockSignals(True)
        combo.setCurrentIndex(LANGUAGE_VISIBLE_INDEX)
        combo.blockSignals(False)
    if getattr(combo, '_hidden_items', None):
        return
    combo._hidden_items = items[LANGUAGE_VISIBLE_INDEX + 1:]
    combo.items = items[:LANGUAGE_VISIBLE_INDEX + 1]
    combo.update()


def _hide_nav_page(window, attribute: str):
    page = getattr(window, attribute, None)
    nav = getattr(window, 'navigationInterface', None)
    if page is None or nav is None:
        return
    route = page.objectName()
    item = nav.widget(route)
    if item is None:
        return
    item.hide()
    item.setFixedHeight(0)
    item.setMinimumHeight(0)
    item.setMaximumHeight(0)


def apply(window):
    """主窗口显示后调用：收起暂不支持的语言项与暂不需要的导航页。"""
    if window is None:
        return

    def _run(win=window):
        try:
            _restrict_language(getattr(win, 'setting_tab', None))
            for attribute in HIDDEN_NAV_PAGES:
                _hide_nav_page(win, attribute)
        except Exception as error:  # noqa: BLE001 - 界面裁剪失败不影响主流程
            logger.warning(f'shell patch skipped: {error}')

    # 等导航与设置页都完成首次布局后再隐藏
    QTimer.singleShot(0, _run)
