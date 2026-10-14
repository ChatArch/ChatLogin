"""New-service factory; no production accounts or credentials are generated."""
from contextlib import asynccontextmanager
from html import escape

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse

from chatlogin import Role
from chatlogin.account_ui import AccountMenuUI
from chatlogin.managed_web import create_managed_auth


def create_app(*, instance: str, origin: str, prefix: str = "/auth", users=None,
               pages: bool = True, allow_insecure_loopback: bool = False,
               menu_ui: AccountMenuUI | None = None) -> FastAPI:
    owns_users = users is None
    auth = create_managed_auth(instance, origin=origin, prefix=prefix, users=users,
                               pages=pages, allow_insecure_loopback=allow_insecure_loopback)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            if owns_users:
                auth.users.close()

    app = FastAPI(lifespan=lifespan)
    app.state.chatlogin_auth = auth
    app.include_router(auth.router)

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        menu = await auth.render_account_menu(request, ui=menu_ui)
        navigation = await auth.navigation_from_request(request)
        assets = escape(str(navigation["assets_path"]), quote=True)
        styles = (f'<link rel="stylesheet" href="{assets}/login.css">'
                  f'<link rel="stylesheet" href="{assets}/users.css">') if assets else ""
        response = HTMLResponse(
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>新服务接入示例</title>{styles}</head><body class="chatlogin-page">'
            '<main class="chatlogin" data-appearance="system"><section class="chatlogin__panel">'
            '<header class="chatlogin-users__header"><h1>示例服务</h1>'
            f'{menu}</header><p class="chatlogin__subtitle">本页复用 ChatLogin 登录、账号与用户管理入口。</p>'
            '</section></main></body></html>')
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.get("/private")
    async def private(principal=Depends(auth.current_user)):
        return principal.as_dict()

    @app.get("/operator")
    async def operator(principal=Depends(auth.roles(Role.ADMIN, Role.OWNER))):
        return {"user_id": principal.user_id}

    return app
