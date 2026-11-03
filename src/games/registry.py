"""profile 名字 → 适配器类的注册表。

游戏模块自己调用 :func:`register`，框架在这里按配置里的 ``game_profile``
惰性导入。这样 ``base_frame`` 不 import 任何具体游戏，模板使用者也不会被
强制绑定到某个游戏上。
"""

import importlib

from src.games.base import GameAdapter

# profile -> "module:Class"
_PROFILES: dict[str, str] = {}


def register(profile: str, target: str) -> None:
    """注册一个游戏适配器。

    Args:
        profile: 配置里 ``game_profile`` 使用的名字。
        target: ``"包路径:类名"``，例如 ``"src.games.crosscore:CrossCoreAdapter"``。
    """
    if not profile or ':' not in target:
        raise ValueError(f'invalid adapter registration: {profile!r} -> {target!r}')
    _PROFILES[profile] = target


def profiles() -> list[str]:
    return sorted(_PROFILES)


def create(profile: str) -> GameAdapter | None:
    """按名字实例化适配器；未注册返回 None（调用方按 SKIPPED 处理）。"""
    target = _PROFILES.get(profile)
    if not target:
        return None
    module_name, class_name = target.split(':', 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return cls()
