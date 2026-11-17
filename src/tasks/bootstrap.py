"""启动层薄壳：批次去重 + 调用 ``runtime.game.start`` + 记日志。

真正的状态机在 :mod:`src.runtime.game`；这里只回答一个问题——
「这次任务执行要不要做启动检查」。
"""

from src.games.base import BootstrapConfig, BootstrapResult
from src.games.registry import load as load_profiles
from src.runtime import game
from src.runtime.session import session

_CONFIG_FIELDS = ('boot_timeout', 'enter_timeout', 'poll_interval', 'force_restart')


def resolve(task):
    """兼容旧调用：返回 (profile, BootstrapConfig)。"""

    config = getattr(getattr(task, 'executor', None), 'config', None) or {}
    profile = getattr(task, 'game_profile', '') or config.get('game_profile', '') or ''
    raw = config.get('game_bootstrap') or {}
    values = {key: raw[key] for key in _CONFIG_FIELDS if key in raw}
    return profile.strip(), BootstrapConfig(**values)


def ensure_ready(task) -> BootstrapResult:
    """按批次语义决定是否检查，需要时调用 ``game.start``。

    Raises:
        game.GameError: 启动失败。
    """

    if not session.should_check():
        _info(task, 'bootstrap: 本批次已检查过，跳过')
        return BootstrapResult.SKIPPED

    config = getattr(getattr(task, 'executor', None), 'config', None) or {}
    load_profiles(config.get('game_profiles'))
    result = game.start(task=task, profile=getattr(task, 'game_profile', '') or '')
    session.mark_checked()
    return result


def _info(task, message):
    logger = getattr(task, 'log_info', None)
    if callable(logger):
        logger(message)
