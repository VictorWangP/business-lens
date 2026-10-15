"""Restore a trusted deployment archive into an empty /data volume."""
from pathlib import Path
import os
import sys
import tarfile

target = Path('/data').resolve()
if any(target.iterdir()):
    raise SystemExit('/data 非空，拒绝覆盖。请先备份并使用空数据卷。')
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    # Reject escaping paths, links and special files before writing anything.
    for member in archive.getmembers():
        path = (target / member.name).resolve()
        if not path.is_relative_to(target) or not (member.isfile() or member.isdir()):
            raise SystemExit(f'不安全的归档成员：{member.name}')
    archive.extractall(target, filter='data')
for directory, dirs, files in os.walk(target):
    os.chown(directory, 10001, 10001)
    for name in dirs + files:
        os.chown(Path(directory) / name, 10001, 10001)
print('数据已恢复；请确认 deploy/.env 使用原密钥，再启动服务。')
