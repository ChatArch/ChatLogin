"""Generate sanitized npm fixtures from real Python ASGI routes, no server."""
import argparse
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from chatlogin import CallbackBackend, ManagedUsers, MemorySessionStore, Principal, Role, SessionManager, __version__
from chatlogin.fastapi import FastAPIAuth
from chatlogin.managed_web import create_managed_auth
from chatlogin.security import safe_next
from chatlogin.ui import LoginUI, PALETTES, LAYOUTS, APPEARANCES

ORIGIN = 'https://accounts.example.test'
TARGET = Path(__file__).resolve().parents[1] / 'tests/fixtures/http-contract.json'


def sanitized(value):
    if isinstance(value, dict):
        return {key: ('fixture-csrf' if key == 'csrf_token' and item else
                      'fixture-' + value.get('role', 'user') if key == 'user_id' and item else sanitized(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    return value


def app_for(auth):
    child = FastAPI()
    child.include_router(auth.router)
    root = FastAPI()
    root.mount('/portal', child)
    return root


def contracts():
    backend = CallbackBackend(lambda username, password: Principal('fixture-user', 'Fixture User')
                              if (username, password) == ('fixture', 'fixture-password') else None)
    auth = FastAPIAuth(backend, SessionManager(MemorySessionStore(), instance='npm-contract'),
                       origin=ORIGIN, ui=LoginUI())
    with TestClient(app_for(auth), base_url=ORIGIN) as client:
        fixed = {'discovery': client.get('/portal/auth/api').json(),
                 'anonymous': client.get('/portal/auth/session').json()}
        response = client.post('/portal/auth/login', headers={'Origin': ORIGIN},
                               json={'username': 'fixture', 'password': 'fixture-password', 'next': '/workspace'})
        assert response.status_code == 200
        fixed['login'] = response.json()
        fixed['session'] = client.get('/portal/auth/session').json()
        assert client.post('/portal/auth/logout', headers={'Origin': ORIGIN}).status_code == 403
        response = client.post('/portal/auth/logout', headers={'Origin': ORIGIN, 'X-CSRF-Token': response.json()['csrf_token']})
        assert response.status_code == 200
        fixed['logout'] = response.json()
        fixed['after_logout'] = client.get('/portal/auth/session').json()
        for name in ['login.css', 'login.js', 'client.js', 'ui.js', 'account-menu.css']:
            assert client.get('/portal/auth/assets/' + name).status_code == 200

    users = ManagedUsers.in_memory('npm-managed-contract')
    users.bootstrap_owner('owner', 'fixture-owner-password')
    owner = users.authenticate('owner', 'fixture-owner-password')
    users.create_user(owner, 'member', 'fixture-member-password', role=Role.USER, display_name='Fixture Member')
    managed_auth = create_managed_auth('npm-managed-contract', origin=ORIGIN, users=users)
    managed_app = app_for(managed_auth)
    with TestClient(managed_app, base_url=ORIGIN) as client:
        managed = {'discovery': client.get('/portal/auth/api').json(), 'roles': {}}
        for username in ['owner', 'member']:
            with TestClient(managed_app, base_url=ORIGIN) as role_client:
                response = role_client.post('/portal/auth/login', headers={'Origin': ORIGIN},
                                            json={'username': username, 'password': f'fixture-{username}-password'})
                assert response.status_code == 200
                managed['roles'][username] = role_client.get('/portal/auth/session').json()
                assert role_client.get('/portal/auth/api/users').status_code == (200 if username == 'owner' else 403)
    headless = create_managed_auth('npm-headless-contract', origin=ORIGIN, users=ManagedUsers.in_memory('npm-headless-contract'), pages=False)
    with TestClient(app_for(headless), base_url=ORIGIN) as client:
        managed['headless_discovery'] = client.get('/portal/auth/api').json()

    vectors = [None, '', '/', '/workspace?tab=1#details', 'https://evil.example/', '//evil.example/',
               '/\\evil.example/', '/%2f%2fevil.example/', '/%252f%252fevil.example/', '/x%0a',
               '/x%20y', '/x%25', '/x%', '/x%FF', '/中文', '/a/../b', '/%2525252525252f',
               '/x?next=https://other.example', '/' + 'a' * 2048, '/' + '😀' * 1024, '/' + '😀' * 2048]
    default_page = LoginUI().render({'assets_path': '/auth/assets', 'login_url': '/auth/login',
                                    'session_url': '/auth/session', 'next': '/'})
    classes = sorted({name for value in re.findall(r'class="([^"]+)"', default_page) for name in value.split()
                      if name != 'chatlogin-page'})
    return sanitized({'provider_version': __version__, 'fixed': fixed, 'managed': managed,
                      'safe_next': [{'input': value, 'expected': safe_next(value)} for value in vectors],
                      'ui': {'palettes': sorted(PALETTES), 'layouts': sorted(LAYOUTS), 'appearances': sorted(APPEARANCES),
                             'default_classes': classes}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    encoded = json.dumps(contracts(), ensure_ascii=False, indent=2) + '\n'
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != encoded:
            raise SystemExit('HTTP fixtures differ from the real Python provider; regenerate and review them.')
        print('Real Python HTTP and UI contracts verified.')
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(encoded)
        print('Wrote sanitized real-provider fixtures.')
