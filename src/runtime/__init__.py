"""项目运行时层：与具体游戏无关的通用能力。

- :mod:`src.runtime.overlay` 弹窗拦截（随时弹出的网络错误、公告、签到等）
- :mod:`src.runtime.daily`   跨日判定（每日 04:00 刷新）

这些能力由 :class:`src.tasks.MyBaseTask` 统一挂载，业务任务不需要自己写检测。
"""

from src.runtime import daily, overlay

__all__ = ['daily', 'overlay']
