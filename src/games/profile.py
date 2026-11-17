"""Game profile schema.

A profile is a small JSON file that describes how to start, stop and recognise
one game.  It exists so that most games need no Python code at all.
"""

import json
from dataclasses import dataclass
from pathlib import Path

LAUNCH_KINDS = ('android_app', 'desktop_exe', 'none')
STOP_KINDS = ('force_stop', 'none')


class ProfileError(ValueError):
    """Raised when a profile file is missing fields or uses unknown values."""


@dataclass(frozen=True)
class GameProfile:
    """Validated description of one game.

    Attributes:
        name: Display name, used in log messages.
        package: Android package name (also used by ``pidof`` and ``am``).
        launch_kind: One of ``android_app``, ``desktop_exe``, ``none``.
        stop_kind: One of ``force_stop``, ``none``.
        login_template: Template name of the login screen button.
        ready_template: Template name of the in-game (ready) marker.
        launch_command: Command line, only for ``desktop_exe``.
    """

    name: str
    package: str
    launch_kind: str = 'android_app'
    stop_kind: str = 'force_stop'
    login_template: str = ''
    ready_template: str = ''
    launch_command: str = ''

    @property
    def login_enabled(self) -> bool:
        return bool(self.login_template)

    @property
    def ready_enabled(self) -> bool:
        return bool(self.ready_template)


def _text(data, key, *, required=True, owner='profile'):
    value = data.get(key, '')
    if not isinstance(value, str):
        raise ProfileError(f'{owner}: 字段 {key} 必须是字符串，收到 {type(value).__name__}')
    value = value.strip()
    if required and not value:
        raise ProfileError(f'{owner}: 缺少必填字段 {key}')
    return value


def _choice(data, key, choices, default, owner='profile'):
    value = data.get(key, default)
    if value not in choices:
        allowed = '、'.join(choices)
        raise ProfileError(f'{owner}: 字段 {key} 只能是 {allowed}，收到 {value!r}')
    return value


def parse_profile(data, *, owner='profile') -> GameProfile:
    """Build a :class:`GameProfile` from a decoded JSON object.

    Args:
        data: Decoded JSON object.
        owner: Name used in error messages (usually the file name).

    Returns:
        The validated profile.

    Raises:
        ProfileError: If a field is missing, empty or outside its allowed values.
    """
    if not isinstance(data, dict):
        raise ProfileError(f'{owner}: 顶层必须是对象，收到 {type(data).__name__}')

    launch = data.get('launch') or {}
    stop = data.get('stop') or {}
    if not isinstance(launch, dict) or not isinstance(stop, dict):
        raise ProfileError(f'{owner}: launch/stop 必须是对象')

    launch_kind = _choice(launch, 'kind', LAUNCH_KINDS, 'android_app', f'{owner}.launch')
    stop_kind = _choice(stop, 'kind', STOP_KINDS, 'force_stop', f'{owner}.stop')

    launch_command = _text(launch, 'command', required=False, owner=f'{owner}.launch')
    if launch_kind == 'desktop_exe' and not launch_command:
        raise ProfileError(f'{owner}.launch: kind=desktop_exe 时必须提供 command')

    return GameProfile(
        name=_text(data, 'name', owner=owner),
        package=_text(data, 'package', owner=owner),
        launch_kind=launch_kind,
        stop_kind=stop_kind,
        login_template=_text(data.get('login') or {}, 'template', required=False,
                             owner=f'{owner}.login'),
        ready_template=_text(data.get('ready') or {}, 'template', required=False,
                             owner=f'{owner}.ready'),
        launch_command=launch_command,
    )


def load_profile(path) -> GameProfile:
    """Read and validate a profile file.

    Args:
        path: Path to the JSON profile.

    Returns:
        The validated profile.

    Raises:
        ProfileError: If the file is missing, unreadable or invalid.
    """
    file = Path(path)
    if not file.is_file():
        raise ProfileError(f'找不到 profile 文件: {file}')
    try:
        data = json.loads(file.read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError as exc:
        raise ProfileError(f'{file.name}: JSON 解析失败（第 {exc.lineno} 行）') from exc
    return parse_profile(data, owner=file.name)
