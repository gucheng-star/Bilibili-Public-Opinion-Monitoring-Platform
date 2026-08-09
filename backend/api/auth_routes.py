from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.auth import (
    credential_reentry_required,
    generate_qrcode,
    poll_qrcode,
    get_cookie,
    clear_cookie,
    get_accounts,
    switch_account,
)

router = APIRouter(prefix='/api/auth')


class QRCodeStatusRequest(BaseModel):
    """Keep the short-lived QR key out of URLs and access logs."""

    qrcode_key: str = Field(min_length=1, max_length=1024)

@router.get('/qrcode')
async def qr_generate(): return await generate_qrcode()

@router.post('/qrcode/status')
async def qr_status(payload: QRCodeStatusRequest):
    return await poll_qrcode(payload.qrcode_key)

@router.get('/status')
def auth_status():
    return {
        'logged_in': bool(get_cookie()),
        'credential_reentry_required': credential_reentry_required(),
    }

@router.post('/logout')
def logout():
    clear_cookie()
    return {'ok': True}

@router.get('/accounts')
def list_accounts():
    # Cookies are kept only inside the local credential store.  The UI needs
    # display names and stable list positions, never session material.
    return {
        'accounts': [
            {
                'index': int(account.get('index', index)),
                'name': str(account.get('name') or 'B站用户'),
            }
            for index, account in enumerate(get_accounts())
            if isinstance(account, dict)
        ]
    }

@router.post('/accounts/{index}/switch')
def account_switch(index: int):
    ok = switch_account(index)
    return {'ok': ok}
