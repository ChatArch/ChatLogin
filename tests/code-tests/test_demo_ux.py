"""User-facing demo presentation contracts, independent of auth tests."""
import re
import pytest
from fastapi.testclient import TestClient
from chatlogin import __version__
from chatlogin.demo import create_demo_app

@pytest.fixture(scope='module')
def client():
    with TestClient(create_demo_app(origin='http://demo.test'), base_url='http://demo.test') as value:
        yield value

@pytest.mark.parametrize(('route','title'),[
    ('/demo/password/', '固定账号登录'),
    ('/demo/callback/', '自定义页面登录'),
    ('/demo/chatvoice/', '账户库兼容登录'),
])
def test_reader_facing_login_titles(client, route, title):
    assert f'<h1>{title}</h1>' in client.get(route).text

def test_template_configuration_is_compact_and_code_is_optional(client):
    html=client.get('/templates').text
    assert 'class="playground__inputs"' in html
    assert '<details class="config-details">' in html
    assert 'data-copy' in html and 'data-config' in html

def test_home_prioritizes_live_examples_over_reference_material(client):
    html=client.get('/').text
    assert html.index('id="live"') < html.index('id="capability-title"')
    assert '登录体验与接入示例' in html

@pytest.mark.parametrize('route',['/','/templates','/experience/async','/demo/password/','/demo/callback/'])
def test_assets_use_current_build_urls(client, route):
    html=client.get(route).text
    assert f'?v={__version__}' in html
