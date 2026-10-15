#!/usr/bin/env bash
# Run from any working directory. Linux/macOS, Docker Compose v2+, Python 3 for init.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ACTION="${1:-help}"
if [[ "$ACTION" == init ]]; then
  exec python3 "$ROOT/scripts/init_deploy.py"
fi
if [[ "$ACTION" == help ]]; then
  echo 'Usage: scripts/deploy.sh {init|build|up|backup|restore ARCHIVE|status|logs|down}'
  exit 0
fi
[[ -f deploy/.env ]] || { echo '先执行 scripts/deploy.sh init' >&2; exit 1; }
compose() { docker compose --env-file "$ROOT/deploy/.env" -f "$ROOT/compose.prod.yaml" "$@"; }
compose config --quiet

# Preserve which services were running; backups briefly stop writers and requests.
backup() (
  mkdir -p "$ROOT/backups"
  chmod 700 "$ROOT/backups"
  local archive="$ROOT/backups/storage-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz"
  local running
  running="$(compose ps --status running --services)"
  resume() {
    local service
    for service in $running; do
      compose start "$service" >&2 || return 1
    done
  }
  trap resume EXIT
  compose stop web api worker >&2
  # Include app.db, WAL, checkpoints, datasets, evidence and migration snapshots.
  if ! compose run --rm --no-deps -T --user 0 --entrypoint tar migrate -C /data -czf - . > "$archive.part"; then
    rm -f "$archive.part"
    return 1
  fi
  chmod 600 "$archive.part"
  mv "$archive.part" "$archive"
  resume
  trap - EXIT
  echo "备份已保存：$archive"
  echo '另外安全保存 deploy/.env；数据备份不包含解密密钥。'
)

case "$ACTION" in
  build) compose build --pull api web ;;
  up)
    # Validate keys before stopping the currently running application.
    compose run --rm --no-deps -T migrate python -c \
      "from app.config import settings; from app.infrastructure.credentials import cipher; assert len(settings.SECRET_KEY.encode()) >= 32 and settings.SECRET_KEY != 'development-only-change-before-deploy', 'Invalid SECRET_KEY'; cipher()"
    if [[ -n "$(compose ps -aq api worker)" ]]; then backup; fi
    compose stop web api worker
    # Always run migrations, even if an old successful migrate container exists.
    compose run --rm --no-deps -T migrate alembic upgrade head
    compose up -d --no-deps --wait --wait-timeout 180 api worker web
    compose ps
    ;;
  backup) backup ;;
  restore)
    [[ $# -eq 2 && -f "$2" ]] || { echo 'Usage: scripts/deploy.sh restore ARCHIVE.tar.gz' >&2; exit 1; }
    [[ -z "$(compose ps --status running --services)" ]] || { echo '请先 down，恢复仅允许写入空数据卷。' >&2; exit 1; }
    archive_dir="$(cd -- "$(dirname -- "$2")" && pwd)"
    compose run --rm --no-deps -T --user 0 -v "$archive_dir:/backup:ro" migrate \
      python scripts/restore_storage.py "/backup/$(basename -- "$2")"
    ;;
  status) compose ps ;;
  logs) compose logs --tail 200 -f api worker web ;;
  down) compose down ;;
  *) echo "未知操作：$ACTION" >&2; exit 1 ;;
esac
