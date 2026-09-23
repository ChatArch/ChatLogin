"""Patch-release API compatibility and live template navigation."""
from fastapi.testclient import TestClient
import pytest
from chatlogin.demo import create_demo_app
from chatlogin.ui import LoginUI


def test_script_url_preserves_existing_positional_renderer_argument():
    renderer = lambda context: '<h1>host renderer</h1>'
    ui = LoginUI('Title', 'Subtitle', 'indigo', 'card', (), 'chatlogin/login.html', None, renderer)
    assert ui.renderer is renderer
    assert ui.script_url is None
    assert ui.render({}) == '<h1>host renderer</h1>'


def test_quickstart_example_runs_real_login(monkeypatch):
    import runpy
    from pathlib import Path
    source = Path(__file__).resolve().parents[2] / 'examples' / 'quickstart_fastapi.py'
    assert source.is_file()
    monkeypatch.setenv('MY_SITE_LOGIN_PASSWORD', 'synthetic-integration-password')
    monkeypatch.setenv('MY_SITE_ORIGIN', 'http://example.test')
    namespace = runpy.run_path(str(source))
    with TestClient(namespace['app'], base_url='http://example.test') as client:
        assert client.get('/').status_code == 200
        assert client.get('/auth/').status_code == 200
        assert client.get('/private').status_code == 401
        result = client.post('/auth/login', headers={'Origin':'http://example.test'}, json={'username':'operator', 'password':'synthetic-integration-password', 'next':'/private'})
        assert result.status_code == 200
        assert client.get('/private').json()['user_id'] == 'operator'



@pytest.mark.parametrize('path', ['/demo/password/', '/demo/chatvoice/', '/playground/preview'])
def test_demo_fill_controls_have_scoped_stylesheet(path):
    with TestClient(create_demo_app(origin='http://demo.test'), base_url='http://demo.test') as client:
        assert '/assets/demo-login.css' in client.get(path).text
        css = client.get('/assets/demo-login.css')
        assert css.status_code == 200
        assert 'text/css' in css.headers['content-type']
        assert '.demo-fill' in css.text


@pytest.mark.parametrize('path', ['/workspace/password', '/guest?mode=password'])
def test_template_destination_can_render_inside_own_demo_frame(path):
    with TestClient(create_demo_app(origin='http://demo.test'), base_url='http://demo.test') as client:
        response = client.get(path)
        assert response.status_code == 200
        assert "frame-ancestors 'self'" in response.headers['content-security-policy']
        assert 'target="_top"' in response.text
