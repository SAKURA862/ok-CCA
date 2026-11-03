"""游戏适配层。"""

from src.games.base import (
    BootstrapConfig,
    BootstrapError,
    BootstrapResult,
    GameAdapter,
    NullAdapter,
)
from src.games.registry import create, profiles, register

__all__ = [
    'BootstrapConfig',
    'BootstrapError',
    'BootstrapResult',
    'GameAdapter',
    'NullAdapter',
    'create',
    'profiles',
    'register',
]
