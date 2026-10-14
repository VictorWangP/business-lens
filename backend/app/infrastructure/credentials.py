from cryptography.fernet import Fernet, InvalidToken
from app.config import settings

def cipher() -> Fernet:
    if not settings.CREDENTIAL_KEY:
        raise ValueError('请先设置 CREDENTIAL_KEY，再保存或使用凭据')
    return Fernet(settings.CREDENTIAL_KEY.encode())

def encrypt(value: str) -> str:
    return 'enc:' + cipher().encrypt(value.encode()).decode()

def decrypt(value: str) -> str:
    if not value:
        return ''
    if not value.startswith('enc:'):
        raise ValueError('发现旧版明文凭据，请重新保存配置以加密迁移')
    try:
        return cipher().decrypt(value[4:].encode()).decode()
    except InvalidToken as exc:
        raise ValueError('凭据解密失败，请检查 CREDENTIAL_KEY') from exc
