"""Packaged login UI with host-overridable templates."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, select_autoescape

PALETTES = {"indigo", "forest", "amber"}
LAYOUTS = {"card", "split"}
APPEARANCES = {"system", "light", "dark"}


def _local_url(value: str, name: str) -> None:
    # Require canonical, unencoded local URLs: no decoding/normalization surprises.
    if (not isinstance(value, str) or not value.startswith("/")
            or value.startswith("//") or any(c in value for c in ("\\", "%"))
            or any(ord(c) < 33 or ord(c) == 127 for c in value)
            or any(part in {".", ".."} for part in urlsplit(value).path.split("/"))):
        raise ValueError(f"{name} must be a canonical local absolute path")


@dataclass(frozen=True)
class LoginUI:
    """Default renderer with optional trusted host templates/HTML renderer.

    Host renderers return trusted HTML without escaping: the host owns escaping,
    scripts, CSP compatibility and safe endpoint wiring. Template directories are
    trusted code too, not a sandbox. Public CSS variables (``--cl-*``) can be set
    on a host ancestor or the component. Guest links only navigate to a host-owned
    path; the host must implement and authorize guest access independently.
    """

    title: str = "ChatLogin"
    subtitle: str = "登录后继续。"
    palette: str = "indigo"
    layout: str = "card"
    template_dirs: Sequence[str | Path] = field(default_factory=tuple)
    template_name: str = "chatlogin/login.html"
    stylesheet_url: str | None = None
    renderer: Callable[[Mapping[str, object]], str] | None = None
    appearance: str = "system"
    guest_url: str | None = None
    guest_label: str = "以访客身份继续"

    def __post_init__(self) -> None:
        if self.palette not in PALETTES:
            raise ValueError(f"Unknown palette: {self.palette}")
        if self.layout not in LAYOUTS:
            raise ValueError(f"Unknown layout: {self.layout}")
        if self.appearance not in APPEARANCES:
            raise ValueError(f"Unknown appearance: {self.appearance}")
        name = self.template_name
        if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or any(part in {"", ".", ".."} for part in name.split("/"))):
            raise ValueError("template_name must be a safe relative template path")
        if isinstance(self.template_dirs, (str, Path)) or not isinstance(self.template_dirs, Sequence):
            raise TypeError("template_dirs must be a sequence of directory paths")
        for directory in self.template_dirs:
            if not isinstance(directory, (str, Path)) or not Path(directory).is_dir():
                raise ValueError("template_dirs must contain existing directories")
        object.__setattr__(self, "template_dirs", tuple(self.template_dirs))
        if self.renderer is not None and not callable(self.renderer):
            raise TypeError("renderer must be callable")
        for name in ("stylesheet_url", "guest_url"):
            value = getattr(self, name)
            if value is not None:
                _local_url(value, name)
        for name in ("title", "subtitle", "guest_label"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a string")

    def render(self, context: Mapping[str, object]) -> str:
        data = dict(context)
        data.update({
            "title": self.title,
            "subtitle": self.subtitle,
            "palette": self.palette,
            "layout": self.layout,
            "appearance": self.appearance,
            "stylesheet_url": self.stylesheet_url,
            "guest_url": self.guest_url,
            "guest_label": self.guest_label,
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
        env = Environment(loader=ChoiceLoader(loaders), autoescape=select_autoescape(("html", "xml"), default=True))
        return env.get_template(self.template_name).render(**data)
