"""Create private deployment configuration once using only Python's stdlib."""
import base64
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / 'deploy/.env'
template = (root / 'deploy/.env.example').read_text()
content = template.replace('SECRET_KEY=\n', f'SECRET_KEY={secrets.token_urlsafe(48)}\n')
content = content.replace('CREDENTIAL_KEY=\n', f'CREDENTIAL_KEY={base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}\n')
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(f'{target} 已存在，保留现有密钥，不覆盖。')
with os.fdopen(fd, 'w') as output:
    output.write(content)
print(f'已生成 {target}（权限 0600）。请设置访问地址和端口。')
