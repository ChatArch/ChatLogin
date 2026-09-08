"""Run a bounded ChatLogin demo with a synthetic account only.

uvicorn examples.demo_fastapi:app --reload --port 10081
"""
from __future__ import annotations

from fastapi import Depends, FastAPI

from chatlogin import CallbackBackend, LoginRateLimiter, MemorySessionStore, Principal, SessionManager
from chatlogin.fastapi import CookieSettings, FastAPIAuth
from chatlogin.ui import LoginUI


def verify(username: str, password: str) -> Principal | None:
    # Replace this callback with a host-owned user database. Do not store
    # production passwords in source.
    if username == "demo@example.invalid" and password == "synthetic-demo-password":
        return Principal("usr_demo", "Demo user")
    return None


auth = FastAPIAuth(
    CallbackBackend(verify),
    SessionManager(MemorySessionStore(max_sessions=100), instance="demo", ttl=3600),
    origin="http://127.0.0.1:10081",
    prefix="/api/auth",
    ui=LoginUI(title="ChatLogin Demo", subtitle="Use the packaged themed page or replace it."),
    limiter=LoginRateLimiter(limit=10, window=60, max_keys=128),
    cookie=CookieSettings(secure=False, same_site="lax", max_age=3600),
)

app = FastAPI(title="ChatLogin FastAPI demo")
app.include_router(auth.router)


@app.get("/private")
def private(principal=Depends(auth.current_user)):
    return principal.as_dict()
