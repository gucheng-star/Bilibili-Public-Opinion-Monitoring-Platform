import httpx, json, os

AUTH_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'auth.json')

def _load():
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, 'r') as f: return json.load(f)
        except: pass
    return {'cookie': '', 'accounts': []}

def _save(data):
    with open(AUTH_FILE, 'w') as f: json.dump(data, f, indent=2, ensure_ascii=False)

def get_cookie() -> str:
    data = _load()
    return data.get('cookie', '')

def save_cookie(cookie: str):
    data = _load()
    data['cookie'] = cookie
    # Try to get username from nav API (best-effort, non-blocking in background possible)
    try:
        import asyncio
        async def _get_name():
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get('https://api.bilibili.com/x/web-interface/nav',
                    headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com','Cookie':cookie})
                j = r.json()
                return j.get('data',{}).get('uname','Unknown')
        name = asyncio.run(_get_name())
    except: name = 'B站用户'
    # Store in accounts list (deduplicate by cookie prefix)
    accs = data.get('accounts', [])
    cookie_prefix = cookie[:40]
    existing = [a for a in accs if a.get('cookie','')[:40] == cookie_prefix]
    if not existing:
        accs.insert(0, {'cookie': cookie, 'name': name})
        if len(accs) > 5: accs = accs[:5]
    data['accounts'] = accs
    _save(data)

def clear_cookie():
    data = _load()
    data['cookie'] = ''
    _save(data)

def get_accounts() -> list:
    data = _load()
    return data.get('accounts', [])

def switch_account(index: int) -> bool:
    data = _load()
    accs = data.get('accounts', [])
    if 0 <= index < len(accs):
        data['cookie'] = accs[index]['cookie']
        _save(data)
        return True
    return False

async def generate_qrcode() -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            'https://passport.bilibili.com/x/passport-login/web/qrcode/generate',
            headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com'})
        data = r.json()
        if data.get('code') != 0: return {'error':'Failed to generate QR code'}
        return {'url':data['data']['url'],'qrcode_key':data['data']['qrcode_key']}

async def poll_qrcode(qrcode_key: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            'https://passport.bilibili.com/x/passport-login/web/qrcode/poll',
            params={'qrcode_key':qrcode_key},
            headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com'})
        data = r.json()
        if data.get('code') != 0: return {'status':'error','message':'API error'}
        inner = data['data']
        code = inner.get('code',-1)
        if code == 0:
            cookies = r.headers.get('set-cookie','')
            sessdata = ''
            for part in cookies.split(','):
                part = part.strip()
                if part.startswith('SESSDATA='):
                    sessdata = part.split(';')[0]
                    break
            if sessdata:
                save_cookie(sessdata)
            return {'status':'success','message':'Logged in'}
        if code == 86090: return {'status':'scanned','message':'Scanned, confirm on phone'}
        if code == 86101: return {'status':'waiting','message':'Waiting for scan'}
        if code == 86038: return {'status':'expired','message':'QR expired'}
        return {'status':'unknown','message':f'Code {code}'}