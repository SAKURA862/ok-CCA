from PySide6.QtCore import QObject

from ok import Logger

from src.ui import shell_patch, theme

logger = Logger.get_logger(__name__)


class Globals(QObject):

    def __init__(self, exit_event):
        super().__init__()
        # 接管设置页的主题卡片（只打补丁，不改 ok-script 源码）
        theme.install()

    def on_show_main_window(self, window):
        # 主窗口创建完成后，按上次保存的选择应用配色
        theme.attach(window)
        # 隐藏暂不支持的语言项与「任务 / 模板」导航
        shell_patch.apply(window)
