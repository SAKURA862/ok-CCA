"""Game profile self check.

Usage::

    python tools/check_game_profile.py assets/games/example.json

Prints the parsed profile, the six adapter capabilities and exits non-zero when
the file is invalid.  Never touches a device.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.games.profile import ProfileError, load_profile  # noqa: E402
from src.games.template import TemplateGameAdapter  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('用法: python tools/check_game_profile.py <profile.json>')
        return 2

    try:
        profile = load_profile(argv[1])
    except ProfileError as exc:
        print(f'✗ {exc}')
        return 1

    adapter = TemplateGameAdapter(profile)
    print(f'✓ profile: {profile.name}')
    print(f'  package      : {profile.package}')
    print(f'  launch       : {profile.launch_kind}')
    print(f'  stop         : {profile.stop_kind}')
    print(f'  login 模板   : {profile.login_template or "（未配置，视为无登录页）"}')
    print(f'  ready 模板   : {profile.ready_template or "（未配置，视为总是就绪）"}')
    print(f'  adapter      : {type(adapter).__name__}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
