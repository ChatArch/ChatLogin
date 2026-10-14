"""Acceptance regressions for the portable menu and new-service lifecycle."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from chatlogin import CallbackBackend, ManagedUsers, MemorySessionStore, SessionManager
from chatlogin.fastapi import FastAPIAuth
from chatlogin.account_ui import AccountMenuUI
from examples.managed_service import create_app


def test_discovery_separates_contract_and_package_versions(monkeypatch):
    import chatlogin
    monkeypatch.setattr(chatlogin, '__version__', '9.9.9')
    auth = FastAPIAuth(CallbackBackend(lambda u, p: None), SessionManager(MemorySessionStore(), instance='version-probe'), origin='https://app.example.test')
    app = FastAPI()
    app.include_router(auth.router)
    with TestClient(app, base_url='https://app.example.test') as client:
        data = client.get('/auth/api').json()
        assert data['version'] == '9.9.9'
        assert data['schema_version'] == 1


def test_native_menu_is_localized_and_has_floating_panel():
    data = {'identity': 'Member', 'assets_path': '/auth/assets', 'links': [{'key': 'profile', 'label': 'My profile', 'url': '/auth/profile'}]}
    html = AccountMenuUI().render(data)
    assert 'aria-label="账号设置"' in html
    assert 'chatlogin-account-menu__panel' in html
    assert '我的账号' in html
    assert 'Account settings' in AccountMenuUI(language='en').render(data)
    assert 'My profile' in AccountMenuUI(language='en').render(data)
    with pytest.raises(ValueError):
        AccountMenuUI(language='invalid')


def test_example_explicit_loopback_menu_and_shared_service_lifecycle():
    users = ManagedUsers.in_memory('portable-example')
    try:
        users.bootstrap_owner('owner', 'synthetic-owner-password')
        with pytest.raises(ValueError):
            create_app(instance='portable-example', origin='http://127.0.0.1:8000', users=users)
        app = create_app(instance='portable-example', origin='http://127.0.0.1:8000', users=users, allow_insecure_loopback=True, menu_ui=AccountMenuUI(mode='links'))
        assert app.state.chatlogin_auth.users is users
        with TestClient(app, base_url='http://127.0.0.1:8000') as client:
            assert '<details' not in client.get('/').text
            assert '登录' in client.get('/').text
            assert client.get('/auth/api').status_code == 200
        # An injected account service is caller-owned, not destroyed by one app.
        assert users.authenticate('owner', 'synthetic-owner-password') is not None
    finally:
        users.close()


def test_empty_headless_menu_has_no_fake_settings_control():
    assert AccountMenuUI().render({'identity': 'Guest', 'links': [], 'assets_path': ''}) == ''


def test_default_pages_have_one_account_navigation():
    users = ManagedUsers.in_memory('single-navigation')
    try:
        users.bootstrap_owner('owner', 'synthetic-owner-password')
        app = create_app(instance='single-navigation', origin='https://app.example.test', users=users)
        with TestClient(app, base_url='https://app.example.test') as client:
            assert client.post('/auth/login', json={'username': 'owner', 'password': 'synthetic-owner-password'}, headers={'Origin': 'https://app.example.test'}).status_code == 200
            assert client.get('/auth/users').text.count('href="/auth/profile"') == 1
            assert client.get('/auth/profile').text.count('href="/auth/users"') == 1
    finally:
        users.close()
