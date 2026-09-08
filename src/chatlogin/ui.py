"""Packaged login UI with host-overridable templates."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, select_autoescape

PALETTES = {"indigo", "forest", "amber"}
LAYOUTS = {"card", "split"}


@dataclass(frozen=True)
class LoginUI:
    """Default login page renderer; hosts may override templates or render fully."""

    title: str = "ChatLogin"
    subtitle: str = "Sign in to continue."
    palette: str = "indigo"
    layout: str = "card"
    template_dirs: Sequence[str | Path] = field(default_factory=tuple)
    template_name: str = "chatlogin/login.html"
    stylesheet_url: str | None = None
    renderer: Callable[[Mapping[str, object]], str] | None = None

    def __post_init__(self) -> None:
        if self.palette not in PALETTES:
            raise ValueError(f"Unknown palette: {self.palette}")
        if self.layout not in LAYOUTS:
            raise ValueError(f"Unknown layout: {self.layout}")
        if not self.template_name or ".." in Path(self.template_name).parts:
            raise ValueError("template_name must be a safe relative template path")
        if self.stylesheet_url is not None and not self.stylesheet_url.startswith("/"):
            raise ValueError("stylesheet_url must be a local absolute path")

    def render(self, context: Mapping[str, object]) -> str:
        data = dict(context)
        data.update({
            "title": self.title,
            "subtitle": self.subtitle,
            "palette": self.palette,
            "layout": self.layout,
            "stylesheet_url": self.stylesheet_url,
        })
        if self.renderer is not None:
            return self.renderer(data)
        loaders = []
        if self.template_dirs:
            loaders.append(FileSystemLoader([str(Path(path)) for path in self.template_dirs]))
        loaders.append(PackageLoader("chatlogin.web", "templates"))
        env = Environment(loader=ChoiceLoader(loaders), autoescape=select_autoescape(("html", "xml")))
        return env.get_template(self.template_name).render(**data)
