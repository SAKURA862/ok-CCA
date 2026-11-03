"""项目任务基类：统一挂载「启动层」。

所有任务都继承它，于是无论从 GUI（一键日常 / 详情页单跑）、CLI 还是 MCP
执行，``run()`` 之前都会先过一次 :func:`src.tasks.bootstrap.ensure_ready`。

需要跳过的任务设置 ``SKIP_GAME_BOOTSTRAP = True``；需要指定游戏的任务设置
``game_profile = 'crosscore'``，否则使用 ``config['game_profile']``。
"""

import functools

from ok import BaseTask

from src.tasks import bootstrap


class MyBaseTask(BaseTask):
    """项目内所有任务的基类。"""

    # 空字符串 = 不接管启动层，等价于旧行为
    game_profile = ''
    # 个别任务（例如纯本机计算的工具任务）可以显式跳过
    SKIP_GAME_BOOTSTRAP = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bootstrap_done = False

    def __init_subclass__(cls, **kwargs):
        """把子类自己定义的 ``run`` 包一层，前面插入启动层。

        只包装子类 ``__dict__`` 里的 ``run``：继承来的实现已经被包装过，
        没有再包一次的问题；没有定义 ``run`` 的子类保持原样，让 MCP 的
        ``cls.run is BaseTask.run`` 校验照常报错。
        """
        super().__init_subclass__(**kwargs)
        original = cls.__dict__.get('run')
        if original is None or getattr(original, '_game_bootstrap_wrapped', False):
            return

        @functools.wraps(original)
        def run(self, *args, **kwargs):
            self.ensure_game_ready()
            return original(self, *args, **kwargs)

        run._game_bootstrap_wrapped = True
        cls.run = run

    def ensure_game_ready(self):
        """幂等：同一次 run 里重复调用只执行一次。"""
        if self._bootstrap_done or self.SKIP_GAME_BOOTSTRAP:
            return None
        self._bootstrap_done = True
        return bootstrap.ensure_ready(self)
