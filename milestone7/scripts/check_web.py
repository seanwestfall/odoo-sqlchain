"""Authenticate to the local release app and fetch its actual JS/CSS bundles."""
import http.cookiejar,json,re,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];base='http://127.0.0.1:8073'
password=json.loads((ROOT/'.local/release/credentials.json').read_text())['admin_password']
client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
req=urllib.request.Request(base+'/web/session/authenticate',data=json.dumps({'jsonrpc':'2.0','method':'call','params':{'db':'chainsql_release','login':'admin','password':password},'id':1}).encode(),headers={'Content-Type':'application/json'})
response=json.load(client.open(req,timeout=30));assert response.get('result',{}).get('uid'),'Authentication failed'
html=client.open(base+'/odoo',timeout=60).read().decode()
urls=sorted(set(re.findall(r'(?:src|href)="(/web/assets/[^"?]+)',html)))
assert any(x.endswith('.js') for x in urls) and any(x.endswith('.css') for x in urls)
for url in urls:
 with client.open(base+url,timeout=90) as r:assert r.status==200 and len(r.read())>100
out={'authenticated':True,'javascript_and_css_loaded':True,'asset_count':len(urls),'url':base,'credentials_exported':False}
(ROOT/'milestone7/evidence/web.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
