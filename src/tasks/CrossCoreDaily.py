"""交错战线（Cross Core）一键日常任务。

目前只实现「启动游戏并进入游戏」这一步，后续日常步骤直接在 ``run`` 里追加。
启动逻辑放在 :mod:`src.tasks.CrossCoreLauncher`，任何需要游戏在前台的任务都能复用。
"""

from qfluentwidgets import FluentIcon

from src.tasks import CrossCoreLauncher as launcher
from src.tasks.MyBaseTask import MyBaseTask


class CrossCoreDailyTask(MyBaseTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "交错战线·启动"
        self.description = "启动交错战线并点击开始游戏；不在任务列表里显示，由一键日常自动调用。"
        self.icon = FluentIcon.CALORIES
        # 启动步骤是日常流程的一部分，不作为独立任务展示
        self.visible = False
        self.default_config.update({
            "Launch Timeout (Seconds)": 180,
        })
        self.config_description.update({
            "Launch Timeout (Seconds)": "等待「开始游戏」按钮出现的最长秒数，冷启动可调大。",
        })

    def reset_to_start(self):
        # 标记本次尝试已完成恢复，MCP 路径里 run() 不再重复恢复
        self._start_prepared = True
        launcher.reset_to_start(self)

    def verify_start_state(self):
        return launcher.verify_start_state(self)

    def run(self):
        try:
            if not getattr(self, '_start_prepared', False):
                # GUI / CLI 调度器只调用 run()，这里自行恢复并校验起始状态
                self.reset_to_start()
                self.verify_start_state()
            timeout = float(self.config.get("Launch Timeout (Seconds)", 180))
            self.log_info(f"启动交错战线（{launcher.PACKAGE_NAME}），最多等待 {timeout:.0f} 秒")
            launcher.ensure_game_started(self, boot_timeout=timeout)
            self.log_info("已进入交错战线游戏界面，启动步骤完成", notify=True)
        finally:
            self._start_prepared = False


# MCP run_task 需要一个名为 Task 的类
Task = CrossCoreDailyTask
