"""Minimal host app; provide an explicit password through the environment."""
import os
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI
import uvicorn
from chatlogin import MemorySessionStore, PasswordBackend, Principal, SessionManager, hash_password
from chatlogin.fastapi import CookieSettings, FastAPIAuth
from chatlogin.ui import LoginUI

origin = os.environ.get("MY_SITE_ORIGIN", "http://127.0.0.1:8000")
password = os.environ["MY_SITE_LOGIN_PASSWORD"]
backend = PasswordBackend({
    "operator": (Principal("operator", "Operator"), hash_password(password)),
})
app = FastAPI()
auth = FastAPIAuth(
    backend,
    SessionManager(MemorySessionStore(max_sessions=256), instance="my-site", ttl=3600),
    origin=origin,
    ui=LoginUI(),
    cookie=CookieSettings(secure=urlsplit(origin).scheme == "https"),
)
app.include_router(auth.router)

@app.get("/")
def home():
    return {"login": "/auth/?next=/private"}

@app.get("/private")
def private(user=Depends(auth.current_user)):
    return user.as_dict()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, proxy_headers=False)
