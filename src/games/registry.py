"""Profile name -> adapter factory registry.

Lookup order, cheapest first:

1. explicit code registration: ``register('crosscore', 'src.games.crosscore:CrossCoreAdapter')``;
2. ``config['game_profiles']`` entries: either ``"module:Class"`` or a ``.json`` path,
   which is wrapped by :class:`TemplateGameAdapter`;
3. convention: ``src/games/<profile>.py`` exposing ``Adapter``.
"""

import importlib
from pathlib import Path

from src.games.base import GameAdapter
from src.games.template import TemplateGameAdapter

# profile -> "module:Class" or "path/to/profile.json"
_PROFILES: dict[str, str] = {}


def register(profile: str, target: str) -> None:
    """Register one profile source.

    Args:
        profile: Name used by ``game_profile``.
        target: ``"module:Class"`` or a path to a JSON profile.

    Raises:
        ValueError: The profile name is empty or ``target`` has neither ``:`` nor ``.json``.
    """

    if not profile or not (':' in target or target.lower().endswith('.json')):
        raise ValueError(f'invalid adapter registration: {profile!r} -> {target!r}')
    _PROFILES[profile] = target


def load(config: dict | None) -> None:
    """Register every entry of ``game_profiles`` (idempotent)."""

    for profile, target in (config or {}).items():
        if isinstance(target, str) and (':' in target or target.lower().endswith('.json')):
            _PROFILES.setdefault(profile, target)


def profiles() -> list[str]:
    return sorted(_PROFILES)


def _load_module(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return None


def _convention(profile: str):
    """Convention lookup: ``src.games.<profile>.Adapter``, then ``assets/games/<profile>.json``."""

    safe = profile.replace('-', '_')
    module = _load_module(f'src.games.{safe}')
    if module is not None:
        for attr in ('Adapter', f'{safe.title().replace("_", "")}Adapter', 'CrossCoreAdapter'):
            cls = getattr(module, attr, None)
            if isinstance(cls, type):
                return cls

    config_file = Path('assets') / 'games' / f'{safe}.json'
    if config_file.is_file():
        return TemplateGameAdapter.from_file(config_file)
    return None


def create(profile: str) -> GameAdapter | None:
    """Instantiate the adapter for ``profile``; ``None`` when unknown."""

    target = _PROFILES.get(profile)
    if target:
        if target.lower().endswith('.json'):
            return TemplateGameAdapter.from_file(target)
        module_name, class_name = target.split(':', 1)
        return getattr(importlib.import_module(module_name), class_name)()
    found = _convention(profile)
    if isinstance(found, type):
        return found()
    return found


def reset() -> None:
    _PROFILES.clear()
