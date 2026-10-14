"""Optional, host-composable account navigation fragment."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, select_autoescape

from .user_ui import _template_dirs, _template_name
from .ui import _local_url


@dataclass(frozen=True)
class AccountMenuUI:
    mode: str = "gear"
    language: str = "zh-CN"
    template_dirs: Sequence[str | Path] | None = None
    template_name: str = "chatlogin/account-menu.html"
    renderer: Callable[[Mapping[str, object]], str] | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"gear", "links"}:
            raise ValueError("mode must be gear or links")
        if self.language not in {"zh-CN", "en"}:
            raise ValueError("language must be zh-CN or en")
        _template_name(self.template_name)
        object.__setattr__(self, "template_dirs", _template_dirs(self.template_dirs, ()))
        if self.renderer is not None and not callable(self.renderer):
            raise TypeError("renderer must be callable")

    def render(self, context: Mapping[str, object]) -> str:
        data = dict(context)
        for link in data.get("links", ()):
            _local_url(link["url"], "account link")
        if data.get("assets_path"):
            _local_url(data["assets_path"], "assets_path")
        data["mode"] = self.mode
        labels = ({"login": "登录", "profile": "我的账号", "users": "用户管理"}
                  if self.language == "zh-CN" else
                  {"login": "Login", "profile": "My profile", "users": "Manage users"})
        data["links"] = [dict(link, label=labels.get(link.get("key"), link["label"]))
                         for link in data.get("links", ())]
        data["settings_label"] = "账号设置" if self.language == "zh-CN" else "Account settings"
        if data.get("role") == "guest":
            data["identity"] = "访客" if self.language == "zh-CN" else "Guest"
        if self.renderer is not None:
            html = self.renderer(data)
            if not isinstance(html, str):
                raise TypeError("renderer must return trusted HTML as a string")
            return html
        if not data["links"]:
            return ""
        loaders = []
        if self.template_dirs:
            loaders.append(FileSystemLoader([str(path) for path in self.template_dirs]))
        loaders.append(PackageLoader("chatlogin.web", "templates"))
        environment = Environment(loader=ChoiceLoader(loaders), autoescape=select_autoescape(("html", "xml"), default=True))
        return environment.get_template(self.template_name).render(**data)
