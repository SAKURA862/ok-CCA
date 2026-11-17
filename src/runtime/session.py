"""批次会话：让一次用户动作（一键日常）只检查一次游戏状态。

单任务、CLI、MCP 都不进入批次，``should_check()`` 恒为 True，
也就是「每次执行都检查一次」，与用户直觉一致。
"""


class BootstrapSession:
    """记录当前是否处于批量执行中、本批是否已经检查过。"""

    def __init__(self):
        self.batch_active = False
        self.checked = False

    def begin_batch(self):
        """批量执行开始时调用；清空「已检查」标记。"""

        self.batch_active = True
        self.checked = False

    def end_batch(self):
        self.batch_active = False
        self.checked = False

    def should_check(self):
        """True 表示需要执行启动检查；批内第二次及以后返回 False。"""

        return not (self.batch_active and self.checked)

    def mark_checked(self):
        self.checked = True

    def invalidate(self):
        """任务失败后调用：下一个任务会重新检查一次。"""

        self.checked = False

    def reset(self):
        self.batch_active = False
        self.checked = False


session = BootstrapSession()
