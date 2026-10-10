from html.parser import HTMLParser
from importlib import resources
import pytest
from chatlogin.user_ui import UserAdminUI, UserProfileUI

CONTEXT={key:'/auth/'+value for key,value in {'assets_path':'assets','login_url':'','session_url':'session','logout_url':'logout','users_url':'users','profile_url':'profile','users_api_url':'api/users','profile_api_url':'api/profile','owner_transfer_api_url':'api/owner/transfer'}.items()}

class Forms(HTMLParser):
    def __init__(self):
        super().__init__();self.forms={};self.current=None;self.disabled=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form':self.current=a['id'];self.forms[self.current]={'attrs':a,'passwords':[]}
        if tag=='fieldset':self.disabled.append('disabled' in a)
        if tag=='input' and a.get('type')=='password' and self.current:self.forms[self.current]['passwords'].append(any(self.disabled))
    def handle_endtag(self,tag):
        if tag=='fieldset':self.disabled.pop()
        if tag=='form':self.current=None

@pytest.mark.parametrize('ui,ids',[(UserProfileUI, ['cl-password-form']),(UserAdminUI,['cl-new-user-form','cl-owner-transfer-form'])])
def test_credentials_never_have_native_get_fallback_and_start_disabled(ui,ids):
    parsed=Forms();parsed.feed(ui().render(CONTEXT))
    for name in ids:
        f=parsed.forms[name]
        assert f['attrs'].get('method','get').lower()=='post'
        assert f['attrs'].get('action','').startswith('/auth/api/')
        assert f['passwords'] and all(f['passwords'])

def test_submit_is_blocked_before_url_validation_and_async_bootstrap():
    script=(resources.files('chatlogin.web')/'assets/users.js').read_text()
    assert script.index('event.preventDefault()') < script.index('const localURL')
    assert 'data-cl-credential-form' in script
