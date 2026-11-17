"""Unit tests for the config driven game adapter (no device, no game content)."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.games import registry  # noqa: E402
from src.games.profile import ProfileError, load_profile, parse_profile  # noqa: E402
from src.games.template import TemplateGameAdapter  # noqa: E402

PASSED = []
FAILED = []


class FakeBox:
    def __init__(self, x=10, y=20, w=30, h=40):
        self.x, self.y, self.width, self.height = x, y, w, h

    def center(self):
        return (self.x + self.width // 2, self.y + self.height // 2)


class FakeCtx:
    def __init__(self, visible=(), pidof=''):
        self.visible = set(visible)
        self.pidof = pidof
        self.shells = []
        self.clicks = []

    def find(self, template):
        return FakeBox() if template in self.visible else None

    def click_box(self, box):
        self.clicks.append(box.center())

    def shell(self, command, *args, **kwargs):
        self.shells.append(command)
        return self.pidof


def check(name, func):
    try:
        func()
    except Exception as exc:  # noqa: BLE001 - 测试收集器
        FAILED.append((name, f'{type(exc).__name__}: {exc}'))
        print(f'FAIL {name}: {exc}')
    else:
        PASSED.append(name)
        print(f'PASS {name}')


BASE = {
    'name': '示例游戏',
    'package': 'com.example.demo',
    'launch': {'kind': 'android_app'},
    'stop': {'kind': 'force_stop'},
    'login': {'template': 'demo_start'},
    'ready': {'template': 'demo_home'},
}


def profile(**overrides):
    data = json.loads(json.dumps(BASE))
    for key, value in overrides.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return parse_profile(data)


def case_fields():
    p = profile()
    assert (p.name, p.package) == ('示例游戏', 'com.example.demo')
    assert (p.launch_kind, p.stop_kind) == ('android_app', 'force_stop')
    assert p.login_enabled and p.ready_enabled


def case_missing_package():
    try:
        profile(package='')
    except ProfileError as exc:
        assert 'package' in str(exc), str(exc)
    else:
        raise AssertionError('缺 package 应当报错')


def case_bad_launch_kind():
    try:
        profile(launch={'kind': 'magic'})
    except ProfileError as exc:
        assert 'android_app' in str(exc), str(exc)
    else:
        raise AssertionError('未知 launch.kind 应当报错')


def case_desktop_needs_command():
    try:
        profile(launch={'kind': 'desktop_exe'})
    except ProfileError as exc:
        assert 'command' in str(exc), str(exc)
    else:
        raise AssertionError('desktop_exe 缺 command 应当报错')


def case_templates_optional():
    p = profile(login=None, ready=None)
    assert not p.login_enabled and not p.ready_enabled


def case_launch_android():
    adapter = TemplateGameAdapter(profile())
    ctx = FakeCtx()
    adapter.launch(ctx)
    assert 'monkey -p com.example.demo' in ctx.shells[0], ctx.shells


def case_launch_none_is_noop():
    adapter = TemplateGameAdapter(profile(launch={'kind': 'none'}))
    ctx = FakeCtx()
    adapter.launch(ctx)
    assert ctx.shells == [], ctx.shells


def case_stop_force():
    adapter = TemplateGameAdapter(profile())
    ctx = FakeCtx()
    adapter.stop(ctx)
    assert ctx.shells == ['am force-stop com.example.demo'], ctx.shells


def case_is_running():
    adapter = TemplateGameAdapter(profile())
    assert adapter.is_running(FakeCtx(pidof='1234')) is True
    assert adapter.is_running(FakeCtx(pidof='')) is False


def case_login_and_ready():
    adapter = TemplateGameAdapter(profile())
    assert adapter.is_login_screen(FakeCtx(visible={'demo_start'})) is True
    assert adapter.is_login_screen(FakeCtx()) is False
    assert adapter.is_ready(FakeCtx(visible={'demo_home'})) is True
    assert adapter.is_ready(FakeCtx()) is False


def case_ready_without_template():
    adapter = TemplateGameAdapter(profile(ready=None))
    assert adapter.is_ready(FakeCtx()) is True


def case_tap_login():
    adapter = TemplateGameAdapter(profile())
    ctx = FakeCtx(visible={'demo_start'})
    assert adapter.tap_login(ctx) is True
    assert ctx.clicks == [FakeBox().center()], ctx.clicks
    assert adapter.tap_login(FakeCtx()) is False


def case_load_file_and_registry():
    tmp = Path(tempfile.mkdtemp(prefix='profile_', dir=str(ROOT / '.tmp')))
    path = tmp / 'demo.json'
    path.write_text(json.dumps(BASE), encoding='utf-8')
    assert load_profile(path).package == 'com.example.demo'

    registry.reset()
    registry.load({'demo': str(path)})
    adapter = registry.create('demo')
    assert isinstance(adapter, TemplateGameAdapter), adapter
    assert adapter.package_name == 'com.example.demo'
    registry.reset()


def case_registry_module_target():
    registry.reset()
    registry.register('tmpl', 'src.games.template:TemplateGameAdapter')
    try:
        registry.create('tmpl')
    except TypeError:
        pass  # 类构造需要 profile，能走到这一步说明解析正确
    else:
        raise AssertionError('TemplateGameAdapter 无参构造应当失败')
    registry.reset()


def case_registry_unknown():
    registry.reset()
    assert registry.create('nope') is None


def main():
    (ROOT / '.tmp').mkdir(exist_ok=True)
    cases = [
        ('profile.fields', case_fields),
        ('profile.missing_package', case_missing_package),
        ('profile.bad_launch_kind', case_bad_launch_kind),
        ('profile.desktop_needs_command', case_desktop_needs_command),
        ('profile.templates_optional', case_templates_optional),
        ('adapter.launch_android', case_launch_android),
        ('adapter.launch_none', case_launch_none_is_noop),
        ('adapter.stop_force', case_stop_force),
        ('adapter.is_running', case_is_running),
        ('adapter.login_and_ready', case_login_and_ready),
        ('adapter.ready_without_template', case_ready_without_template),
        ('adapter.tap_login', case_tap_login),
        ('registry.load_file', case_load_file_and_registry),
        ('registry.module_target', case_registry_module_target),
        ('registry.unknown', case_registry_unknown),
    ]
    for name, func in cases:
        check(name, func)

    print()
    if FAILED:
        print(f'{len(FAILED)} case(s) failed')
        return 1
    print(f'{len(PASSED)}/{len(cases)} passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
