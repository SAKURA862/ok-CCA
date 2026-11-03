"""游戏适配层：把「怎么启动、怎么判断登录页/大厅」从任务里解耦出来。

框架只依赖这个协议，不依赖任何具体游戏；具体游戏在各自的适配器里实现，
并在 ``src/games/registry.py`` 用 profile 名字注册。

三个判定必须互斥且覆盖全部画面，状态机才能收敛：

* ``is_login_screen`` 标题/登录页——需要点击；
* ``is_ready`` 已进入游戏、可以执行任务——直接放行；
* 两者都不是：加载中、过场、断线——继续等。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class BootstrapResult(str, Enum):
    """启动层的结果。日志与测试都按这个枚举断言。"""

    LAUNCHED = 'launched'            # 本次主动拉起了游戏进程
    TAPPED = 'tapped'                # 游戏已在运行，只点了登录页
    ALREADY_READY = 'already_ready'  # 已在可执行画面，什么都没做
    SKIPPED = 'skipped'              # 未配置 game_profile 或任务显式跳过


class BootstrapError(RuntimeError):
    """启动层无法把游戏带到可执行状态。消息里必须包含阶段与已等待时长。"""


@dataclass(frozen=True)
class BootstrapConfig:
    """来自 ``config['game_bootstrap']``，缺省值就是推荐值。"""

    boot_timeout: float = 180.0    # 拉起进程到出现登录页的上限
    enter_timeout: float = 90.0    # 点击登录按钮到进入游戏的上限
    poll_interval: float = 0.6     # 轮询间隔
    force_restart: bool = False    # True = 每次运行前强制重启游戏


@runtime_checkable
class GameAdapter(Protocol):
    """一个游戏需要提供的最小能力集合。

    ``reset`` 是可选的：没有实现时，``force_restart`` 会被忽略。
    """

    name: str
    package_name: str

    def launch(self, task) -> None:
        """把游戏拉到前台；未运行则启动进程。"""

    def is_login_screen(self, task) -> bool:
        """当前画面是否是「登录页」（例如标题页的开始游戏按钮）。"""

    def is_ready(self, task) -> bool:
        """是否已进入可执行画面（大厅 / 主界面 / 战斗外的主循环）。"""

    def tap_login(self, task) -> bool:
        """点击登录按钮。返回是否成功发出了点击。"""


class NullAdapter:
    """未配置游戏时的占位实现：永远认为已就绪，不做任何动作。"""

    name = 'null'
    package_name = ''

    def launch(self, task):
        return None

    def is_login_screen(self, task):
        return False

    def is_ready(self, task):
        return True

    def tap_login(self, task):
        return False
