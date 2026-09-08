"""Explicit, disposable host example; not a production account service.

Set CHATLOGIN_DEMO_PASSWORD to a synthetic password (at least 12 characters), then:
python -m uvicorn examples.demo_fastapi:create_app --factory --host 127.0.0.1 --port 10081
"""
from __future__ import annotations

import html
import os
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, Response

from chatlogin import MemorySessionStore, PasswordBackend, Principal, SessionManager, hash_password, __version__
from chatlogin.fastapi import CookieSettings, FastAPIAuth
from chatlogin.ui import LoginUI

DEMO_JS = """
document.querySelector('#logout')?.addEventListener('click', async () => {
  const status = document.querySelector('#status');
  try {
    const session = await fetch('/api/auth/session', {credentials: 'same-origin', cache: 'no-store'}).then(r => r.json());
    const response = await fetch('/api/auth/logout', {
      method: 'POST', credentials: 'same-origin',
      headers: {'X-CSRF-Token': session.csrf_token || ''}
    });
    if (!response.ok) throw new Error('Logout failed');
    window.location.reload();
  } catch (_) { status.textContent = 'Unable to sign out. Please retry.'; }
});
"""


def create_app(*, backend=None, origin=None, ui=None):
    """Build only when explicitly requested; real hosts inject their own stores."""
    if backend is None:
        password = os.environ.get('CHATLOGIN_DEMO_PASSWORD', '')
        if len(password) < 12:
            raise ValueError('Set CHATLOGIN_DEMO_PASSWORD to a synthetic password of at least 12 characters')
        backend = PasswordBackend({'demo': (Principal('demo-user', 'Demo user'), hash_password(password))})
    origin = origin or os.environ.get('CHATLOGIN_DEMO_ORIGIN', 'http://127.0.0.1:10081')
    auth = FastAPIAuth(
        backend,
        SessionManager(MemorySessionStore(max_sessions=100), instance='demo', ttl=3600),
        origin=origin,
        prefix='/api/auth',
        ui=ui if ui is not None else LoginUI(title='ChatLogin 演示', subtitle='默认页面可用，宿主样式可替换。'),
        cookie=CookieSettings(secure=urlsplit(origin).scheme == 'https', max_age=3600),
    )
    app = FastAPI(title='ChatLogin host example', docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(auth.router)
    app.state.chatlogin_auth = auth

    @app.get('/health')
    def health():
        return {'version': __version__, 'mode': 'disposable-demo'}

    @app.get('/', response_class=HTMLResponse)
    def home(request: Request):
        session = auth.sessions.resolve(request.cookies.get(auth.cookie.name))
        label = html.escape(session.principal.display_name) if session else 'Guest'
        action = '<button id="logout">退出登录</button>' if session else '<a href="/api/auth/?next=/">登录</a>'
        return HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>ChatLogin host demo</title>'
                            '<h1>宿主网站</h1><p id="identity">' + label + '</p>' + action +
                            '<p id="status" role="status"></p><script defer src="/demo.js"></script></html>',
                            headers={'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'"})

    @app.get('/demo.js')
    def script():
        return Response(DEMO_JS, media_type='application/javascript', headers={'Cache-Control': 'no-store'})

    @app.get('/private')
    def private(principal=Depends(auth.current_user)):
        return principal.as_dict()

    return app
