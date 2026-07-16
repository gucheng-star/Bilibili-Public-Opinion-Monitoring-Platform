from fastapi import APIRouter
from services.auth import generate_qrcode, poll_qrcode, get_cookie, clear_cookie, get_accounts, switch_account

router = APIRouter(prefix='/api/auth')

@router.get('/qrcode')
async def qr_generate(): return await generate_qrcode()

@router.get('/qrcode/status')
async def qr_status(qrcode_key: str): return await poll_qrcode(qrcode_key)

@router.get('/status')
def auth_status(): return {'logged_in': bool(get_cookie())}

@router.post('/logout')
def logout():
    clear_cookie()
    return {'ok': True}

@router.get('/accounts')
def list_accounts(): return {'accounts': get_accounts()}

@router.post('/accounts/{index}/switch')
def account_switch(index: int):
    ok = switch_account(index)
    return {'ok': ok}