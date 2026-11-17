"""Config driven game adapter.

``TemplateGameAdapter`` implements the :class:`GameAdapter` protocol purely from
a :class:`GameProfile`, so a new game normally needs a JSON file and two
templates only.
"""

from src.games.base import GameAdapter  # noqa: F401  (protocol reference)
from src.games.profile import GameProfile, load_profile


class TemplateGameAdapter:
    """Adapter whose every behaviour comes from a :class:`GameProfile`.

    Attributes:
        profile: The profile driving this adapter.
    """

    def __init__(self, profile: GameProfile):
        self.profile = profile

    @classmethod
    def from_file(cls, path) -> 'TemplateGameAdapter':
        """Load a profile file and wrap it."""
        return cls(load_profile(path))

    @property
    def name(self) -> str:
        return self.profile.name

    @property
    def package_name(self) -> str:
        return self.profile.package

    def launch(self, ctx) -> None:
        """Start the game using ``launch.kind``."""
        kind = self.profile.launch_kind
        if kind == 'none':
            return
        if kind == 'android_app':
            ctx.shell(
                f'monkey -p {self.profile.package} '
                f'-c android.intent.category.LAUNCHER 1'
            )
            return
        raise NotImplementedError(
            'desktop_exe 需要自定义适配器（TemplateGameAdapter 只支持 android_app）'
        )

    def stop(self, ctx) -> None:
        """Close the game using ``stop.kind``."""
        if self.profile.stop_kind == 'force_stop':
            ctx.shell(f'am force-stop {self.profile.package}')

    def is_running(self, ctx) -> bool:
        """Return whether the package has a live process."""
        try:
            output = ctx.shell(f'pidof {self.profile.package}')
        except Exception:  # noqa: BLE001 - 设备异常按「没在跑」处理
            return False
        if not output:
            return False
        text = output.decode('utf-8', 'ignore') if isinstance(output, bytes) else str(output)
        text = text.strip()
        return any(ch.isdigit() for ch in text)

    def is_login_screen(self, ctx) -> bool:
        """Return whether the login anchor is visible."""
        if not self.profile.login_enabled:
            return False
        return ctx.find(self.profile.login_template) is not None

    def is_ready(self, ctx) -> bool:
        """Return whether the in-game anchor is visible."""
        if not self.profile.ready_enabled:
            return True
        return ctx.find(self.profile.ready_template) is not None

    def tap_login(self, ctx) -> bool:
        """Click the login anchor; return whether a click was sent."""
        if not self.profile.login_enabled:
            return False
        box = ctx.find(self.profile.login_template)
        if box is None:
            return False
        ctx.click_box(box)
        return True
