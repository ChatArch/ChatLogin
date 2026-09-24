"""Two real identities, isolated sessions and host-enforced private resources."""
import pytest
from fastapi.testclient import TestClient
from chatlogin.demo import create_demo_app

ORIGIN='http://demo.test'
MODES=('password','callback','async','chatvoice')
A={'username':'demo','password':'chatlogin-demo'}
B={'username':'demo-b','password':'chatlogin-demo-b'}

def login(client, mode, account, csrf=None):
    headers={'Origin':ORIGIN}
    if csrf:headers['X-CSRF-Token']=csrf
    return client.post(f'/demo/{mode}/login',headers=headers,json={**account,'next':f'/workspace/{mode}'})


def test_public_account_metadata_contains_only_two_explicit_synthetic_accounts(monkeypatch):
    monkeypatch.setenv('CHATLOGIN_REAL_PASSWORD','must-not-appear-canary')
    with TestClient(create_demo_app(origin=ORIGIN),base_url=ORIGIN) as client:
        response=client.get('/api/demo/accounts')
        assert response.status_code==200
        assert response.json()['synthetic'] is True
        assert {r['username'] for r in response.json()['accounts']}=={'demo','demo-b'}
        assert 'must-not-appear-canary' not in response.text
        assert response.headers['cache-control']=='no-store'


@pytest.mark.parametrize('mode',MODES)
def test_two_accounts_have_real_bidirectional_data_isolation(mode):
    app=create_demo_app(origin=ORIGIN)
    with TestClient(app,base_url=ORIGIN) as a:
        b=TestClient(app,base_url=ORIGIN)
        try:
            base=f'/api/demo/{mode}/records'
            assert a.get(base).status_code==401
            ra=login(a,mode,A);rb=login(b,mode,B)
            assert ra.status_code==rb.status_code==200
            ua,ub=ra.json()['user'],rb.json()['user']
            assert ua['user_id']!=ub['user_id']
            da=a.get(base);db=b.get(base)
            assert da.status_code==db.status_code==200
            ar=da.json()['records'];br=db.json()['records']
            assert len(ar)==len(br)==1
            ar,br=ar[0],br[0]
            assert ar['owner_id']==ua['user_id'] and br['owner_id']==ub['user_id']
            assert ar['id']!=br['id'] and ar['note']!=br['note']
            assert br['note'] not in da.text and ar['note'] not in db.text
            for client,own,other,csrf in ((a,ar,br,ra.json()['csrf_token']),(b,br,ar,rb.json()['csrf_token'])):
                assert client.get(base+'/'+own['id']).status_code==200
                denied=client.get(base+'/'+other['id'])
                assert denied.status_code==403 and other['note'] not in denied.text
                assert denied.headers['cache-control']=='no-store'
                denied=client.post(base+'/'+other['id']+'/touch',headers={'Origin':ORIGIN,'X-CSRF-Token':csrf})
                assert denied.status_code==403
                assert client.post(base+'/'+own['id']+'/touch',headers={'Origin':ORIGIN}).status_code==403
                changed=client.post(base+'/'+own['id']+'/touch',headers={'Origin':ORIGIN,'X-CSRF-Token':csrf})
                assert changed.status_code==200 and changed.json()['record']['revision']==own['revision']+1
            assert a.get(base+'/'+ar['id']).json()['record']['revision']==1
            assert b.get(base+'/'+br['id']).json()['record']['revision']==1
            assert a.post(f'/demo/{mode}/logout',headers={'Origin':ORIGIN,'X-CSRF-Token':ra.json()['csrf_token']}).status_code==200
            assert a.get(base).status_code==401
            assert b.get(base).status_code==200
        finally:b.close()


@pytest.mark.parametrize('mode',MODES)
def test_account_switch_and_owner_forgery_cannot_retarget_private_data(mode):
    with TestClient(create_demo_app(origin=ORIGIN),base_url=ORIGIN) as client:
        first=login(client,mode,A);assert first.status_code==200
        own=client.get(f'/api/demo/{mode}/records').json()['records'][0]
        headers={'Origin':ORIGIN,'X-CSRF-Token':first.json()['csrf_token']}
        bad=client.post(f'/api/demo/{mode}/records/{own["id"]}/touch',headers=headers,json={'owner_id':'forged','revision':900})
        assert bad.status_code==400
        assert client.get(f'/api/demo/{mode}/records/{own["id"]}').json()['record']['revision']==0
        assert login(client,mode,B).status_code==403
        changed=login(client,mode,B,first.json()['csrf_token']);assert changed.status_code==200
        assert changed.json()['user']['user_id']!=first.json()['user']['user_id']
        assert client.get(f'/api/demo/{mode}/records/{own["id"]}').status_code==403
        assert client.get(f'/demo/{mode}/session').json()['user']['user_id']==changed.json()['user']['user_id']
        # A guest link must not lie about a still-valid logged-in identity.
        assert 'data-state="authenticated"' in client.get('/guest',params={'mode':mode}).text
