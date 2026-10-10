"""Packaged managed-account pages built on the LoginUI presentation contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, select_autoescape

from .ui import LoginUI


_LANGUAGES = {"zh-CN", "en"}


def _template_name(value: str) -> None:
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ValueError("template_name must be a safe relative template path")


def _template_dirs(value: Sequence[str | Path] | None, fallback: Sequence[str | Path]) -> tuple[str | Path, ...]:
    if value is None:
        return tuple(fallback)
    if isinstance(value, (str, Path)) or not isinstance(value, Sequence):
        raise TypeError("template_dirs must be a sequence of directory paths")
    directories = tuple(value)
    for directory in directories:
        if not isinstance(directory, (str, Path)) or not Path(directory).is_dir():
            raise ValueError("template_dirs must contain existing directories")
    return directories


@dataclass(frozen=True)
class _UserUI:
    """Shared trusted renderer mechanics for the two managed-account pages."""

    login_ui: LoginUI = field(default_factory=LoginUI)
    title: str = "ChatLogin"
    subtitle: str = ""
    template_dirs: Sequence[str | Path] | None = None
    template_name: str = "chatlogin/users.html"
    renderer: Callable[[Mapping[str, object]], str] | None = None
    language: str = "zh-CN"

    def __post_init__(self) -> None:
        if not isinstance(self.login_ui, LoginUI):
            raise TypeError("login_ui must be a LoginUI")
        _template_name(self.template_name)
        object.__setattr__(self, "template_dirs", _template_dirs(self.template_dirs, self.login_ui.template_dirs))
        if self.renderer is not None and not callable(self.renderer):
            raise TypeError("renderer must be callable")
        if self.language not in _LANGUAGES:
            raise ValueError("language must be zh-CN or en")
        for name in ("title", "subtitle"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a string")

    def render(self, context: Mapping[str, object]) -> str:
        data = dict(context)
        data.update({
            "title": self.title,
            "subtitle": self.subtitle,
            "palette": self.login_ui.palette,
            "layout": self.login_ui.layout,
            "appearance": self.login_ui.appearance,
            "stylesheet_url": self.login_ui.stylesheet_url,
            "script_url": self.login_ui.script_url,
            "language": self.language,
        })
        if self.renderer is not None:
            html = self.renderer(data)
            if not isinstance(html, str):
                raise TypeError("renderer must return trusted HTML as a string")
            return html
        loaders = []
        if self.template_dirs:
            loaders.append(FileSystemLoader([str(Path(path)) for path in self.template_dirs]))
        loaders.append(PackageLoader("chatlogin.web", "templates"))
        environment = Environment(
            loader=ChoiceLoader(loaders),
            autoescape=select_autoescape(("html", "xml"), default=True),
        )
        return environment.get_template(self.template_name).render(**data)


@dataclass(frozen=True)
class UserAdminUI(_UserUI):
    """Owner/admin management page with the same theme inputs as ``LoginUI``."""

    title: str = "用户管理"
    subtitle: str = "管理此实例中的账号、角色和访问状态。"
    template_name: str = "chatlogin/users.html"


@dataclass(frozen=True)
class UserProfileUI(_UserUI):
    """Authenticated user's profile and password page."""

    title: str = "个人账号"
    subtitle: str = "更新显示名称或修改自己的密码。"
    template_name: str = "chatlogin/profile.html"


__all__ = ["UserAdminUI", "UserProfileUI"]
