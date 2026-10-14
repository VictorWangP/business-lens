"""Initialize local configuration without overwriting an existing .env or printing secrets."""
from pathlib import Path
import secrets
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    raise SystemExit('backend/.env 已存在，未修改；请根据 .env.example 补齐配置。')
value = (root / '.env.example').read_text()
value = value.replace('SECRET_KEY=replace-with-a-random-secret', 'SECRET_KEY=' + secrets.token_urlsafe(48))
value = value.replace('CREDENTIAL_KEY=\n', 'CREDENTIAL_KEY=' + Fernet.generate_key().decode() + '\n')
with target.open('x') as file:
    file.write(value)
target.chmod(0o600)
print('已创建 backend/.env；密钥未输出。请启动应用后在模型设置中配置对话及嵌入模型。')
