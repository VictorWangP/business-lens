# 远程 Linux 容器部署

本方案适用于单台 Linux 服务器：Nginx 提供前端并代理 `/api/`，一个 API 进程、一个统一 worker 共享本机 Docker 数据卷。应用库使用 SQLite，业务文件使用 DuckDB / SQLite，任务由数据库调度，无需 Redis。镜像同时安装 `requirements-postgres.txt` 中固定版本的驱动，支持连接外部 PostgreSQL 业务数据源。已有 `compose.yaml` 保留为后端开发配置；生产部署使用 `compose.prod.yaml`。

## 1. 服务器准备

安装 Docker Engine 与 Docker Compose 插件，参考 [Docker 官方 Linux 安装说明](https://docs.docker.com/engine/install/)。确认 Docker 服务开机启动，并允许部署用户运行 Docker。安装 Git、Python 3（仅生成配置需要）、curl。Dockerfile 的 Python、Node 和 Nginx 基础镜像通过 DaoCloud 的 Docker Hub 代理获取；构建仍需访问 PyPI、npm registry，以及 tiktoken 的 tokenizer 下载地址。运行时需要访问实际配置的模型服务和业务数据库。

```bash
docker version
docker compose version
sudo systemctl enable --now docker
```

建议先准备 2 核、4 GiB 内存与足够保存业务数据及备份的本地 SSD，实际容量和模型并发按负载调整。数据卷需要支持本地文件锁；不要放在 NFS，也不要直接横向扩容 API 或统一 worker。当前常问 worker 有独占锁。

## 2. 传输项目并初始化

将当前源码（包括尚未提交的新文件）传输到服务器，例如本地执行：

```bash
rsync -av --include='.env.example' --exclude='.git' --exclude='.env' \
  --exclude='.env.*' --exclude='node_modules' --exclude='.venv' \
  --exclude='venv' --exclude='__pycache__' --exclude='dist' \
  --exclude='storage-v2' --exclude='backups' --exclude='.DS_Store' \
  ./ deploy@YOUR_SERVER:/opt/businesslens/
```

也可以从已经包含全部部署文件的 Git 提交克隆。服务器上：

```bash
cd /opt/businesslens
bash scripts/deploy.sh init
```

脚本创建权限为 `0600` 的 `deploy/.env`，生成独立 JWT 密钥与 Fernet 凭据密钥，已有文件不会覆盖。按需编辑：

```dotenv
IMAGE_TAG=20261015-1
DOCKER_PLATFORM=linux/amd64
HTTP_BIND=127.0.0.1
HTTP_PORT=8080
CORS_ORIGINS=["https://lens.example.com"]
```

前端使用同源 `/api`，不需要 Vite 构建参数。若只通过 SSH 隧道访问，保留默认绑定即可；需要内网直接访问时改为 `HTTP_BIND=0.0.0.0`，在安全组/防火墙中限制访问范围，浏览器访问 `http://服务器IP:8080`。公网使用 HTTPS 入口，见下节。

**不要更换已有部署的 `CREDENTIAL_KEY`**，模型及数据库凭据依赖它解密。升级和恢复都需保留 `deploy/.env`；独立安全备份该文件。后端开发用的 `backend/.env` 不会打入镜像，也不会被生产 Compose 使用。

## 3. 构建与首次启动

```bash
bash scripts/deploy.sh build
bash scripts/deploy.sh up
bash scripts/deploy.sh status
curl --fail http://127.0.0.1:8080/api/health
curl --fail http://127.0.0.1:8080/api/ready
```

`up` 检查密钥，停止旧服务，执行 Alembic，再等待 API 和 Nginx 健康检查通过。迁移失败时不会启动新版服务，保留失败输出处理；不要忽略迁移错误。Compose 直接启动时同样使用 [迁移完成和健康检查依赖](https://docs.docker.com/compose/how-tos/startup-order/)。API 和 worker 使用 UID/GID `10001:10001`，首次创建的数据卷自动获得可写目录。前端采用多阶段构建，最终镜像仅包含 Nginx 和静态文件。

只有 web 的端口映射到主机；API 与数据卷不对外暴露。容器日志滚动保留每服务约 30 MiB。服务设置 `unless-stopped`；主机重启后 Docker 会恢复先前运行的服务。健康检查失败只会标记 unhealthy，Docker 不会仅因此自动重启容器。worker 目前没有应用级存活探针，`up` 对它只验证进程启动；还需检查日志及实际任务。

首次验收：注册用户 → 配置支持工具调用的模型 → 导入 CSV/Excel 或连接数据库 → 建业务空间 → 发起 SQL 问答。确认流式输出、停止生成、刷新恢复、上传、常问任务和数据持久化。Nginx [关闭响应缓冲并延长代理读取超时](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)以支持 SSE。默认上传入口允许 55 MiB 请求，应用文件上限仍为 50 MiB。

## 4. 域名和 HTTPS

默认容器监听主机 `127.0.0.1:8080`，可以接已有 HTTPS 网关，或在主机配置 Nginx。证书通过现有证书管理系统签发并续期。示例（替换域名和证书路径）：

```nginx
server {
    listen 80;
    server_name lens.example.com;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name lens.example.com;
    ssl_certificate /etc/letsencrypt/live/lens.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/lens.example.com/privkey.pem;
    client_max_body_size 55m;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 1800s;
        proxy_send_timeout 1800s;
    }
}
```

公网安全组仅放行需要的 SSH、80、443。没有域名时可使用隧道：`ssh -L 8080:127.0.0.1:8080 deploy@YOUR_SERVER`，本地访问 `http://localhost:8080`。

## 5. 数据、升级与备份

固定 Compose 项目名为 `businesslens`，数据卷为 `businesslens_app-data`，容器中固定挂载 `/data`。其中包括应用库、checkpoint、上传的数据集、证据以及迁移备份。日常 `down` 保留数据，**不要使用 `down -v`**。数据库连接中的 `localhost` 指容器自身；连接主机上的数据库可使用 `host.docker.internal`，数据库还需允许容器网段访问。

升级前保留旧版源码、旧 `IMAGE_TAG` 和对应镜像。更新源码后设定新的 `IMAGE_TAG`，执行：

```bash
bash scripts/deploy.sh build
bash scripts/deploy.sh up
```

也可以在本地构建镜像，再传到服务器运行。**镜像必须匹配服务器架构**：服务器执行 `uname -m`，`x86_64` 对应 `linux/amd64`，`aarch64` 对应 `linux/arm64`。在本机 `deploy/.env` 中设置相同平台和版本，例如：

```dotenv
IMAGE_TAG=20261015-1
DOCKER_PLATFORM=linux/amd64
```

启动本机 Docker Desktop/Engine 后，在项目根目录打包：

```bash
bash scripts/deploy.sh package-images
```

脚本会按指定平台构建 API 和前端镜像，检查镜像架构，再生成 `artifacts/businesslens-images-20261015-1-linux-amd64.tar.gz` 及 SHA-256 校验文件。镜像构建需要本地 Docker daemon 和网络；Apple Silicon 可通过 Docker Desktop 为 `linux/amd64` 构建，但速度可能较慢。

将项目部署文件、镜像包和校验文件传到服务器。务必在服务器保留其自己的 `deploy/.env` 密钥；只同步 `IMAGE_TAG` 和 `DOCKER_PLATFORM` 设置，不要用本机 `.env` 覆盖服务器密钥：

```bash
ssh deploy@YOUR_SERVER 'mkdir -p /opt/businesslens/artifacts'
scp artifacts/businesslens-images-20261015-1-linux-amd64.tar.gz \
  artifacts/businesslens-images-20261015-1-linux-amd64.tar.gz.sha256 \
  deploy@YOUR_SERVER:/opt/businesslens/artifacts/
```

在 Linux 服务器上加载并启动：

```bash
cd /opt/businesslens
cd artifacts && sha256sum -c businesslens-images-20261015-1-linux-amd64.tar.gz.sha256 && cd ..
docker load -i artifacts/businesslens-images-20261015-1-linux-amd64.tar.gz
# 确保服务器 deploy/.env 中 IMAGE_TAG 和 DOCKER_PLATFORM 与镜像包一致
bash scripts/deploy.sh up
```

发布新版本时使用新的 `IMAGE_TAG`，本地和服务器保持一致。服务器不需要构建镜像，但仍需要 Docker Compose、项目的 Compose/运维脚本，以及配置好的 `deploy/.env`。数据库迁移和数据备份流程与服务器构建方案相同。

检测到已有 API/worker 容器时，`up` 会先进行一次全卷备份，再迁移。备份与升级会有短暂停机；请先等待重要任务完成。备份脚本停止 API、worker 和 web，确保 SQLite WAL、checkpoint 与业务文件一起归档，再恢复此前运行的服务。手动备份：

```bash
bash scripts/deploy.sh backup
```

归档保存在 `backups/storage-时间-进程号.tar.gz`，权限 `0600`。备份前确保空间充足；失败会尝试恢复原服务。备份需要已有后端镜像，归档容器临时使用 root 读取数据卷。`deploy/.env` 需另行保存；将数据备份和密钥备份安全转存到另一台机器，并定期演练恢复。升级迁移可能删除旧表，不支持仅切换旧镜像回退数据库；需要使用旧源码/镜像及升级前全卷备份共同恢复。

## 6. 恢复与回退

恢复只接受空数据卷，拒绝覆盖现存文件。先验证归档可读，并保存当前数据备份，再停止服务：

```bash
gzip -t backups/storage-YOUR_BACKUP.tar.gz
bash scripts/deploy.sh backup
bash scripts/deploy.sh down
```

接下来这条命令会**删除当前部署的数据卷**，仅在确认已有可靠备份、准备恢复时手动执行：

```bash
docker volume rm businesslens_app-data
```

切回与备份匹配的源码和 `IMAGE_TAG`，确认 `deploy/.env` 保留原来的两个密钥；若在新服务器恢复，先安全复制原 `.env`。然后：

```bash
# 若对应镜像不在本机，使用匹配的源码 build 或从镜像仓库拉取。
bash scripts/deploy.sh restore backups/storage-YOUR_BACKUP.tar.gz
bash scripts/deploy.sh up
```

脚本校验归档路径，拒绝链接/特殊文件，恢复后设置 UID/GID 为 `10001:10001`。仅使用可信部署归档；失败时保持停机并检查日志。不要用升级后的镜像去恢复旧版再期待回退，因为 `up` 会执行该镜像的迁移。

## 7. 现有本地数据迁移注意

默认方案在服务器初始化全新实例。本地 `storage-v2` 不能仅复制到 `/data` 就使用：文件型数据源连接凭据中保存了加密后的绝对路径，Mac 路径在 Linux 容器不存在，且连接器会验证路径位于授权用户目录。推荐在服务器重新注册、配置模型、导入原始 CSV/Excel 并创建业务空间。若必须保留用户、历史与业务数据，需要另外设计路径重映射迁移，保留原 `CREDENTIAL_KEY`，在停机副本上验证后再上线。

由本生产方案创建的备份固定使用 `/data`，可直接在另一台 Linux 服务器恢复。不要混用原开发 Compose 的 `rag-langgraph_langgraph-artifacts` 卷；若手工接入旧 root 所有的卷，还需先离线备份，再修正所有权为 `10001:10001`。

## 8. 日常运维

```bash
bash scripts/deploy.sh status
bash scripts/deploy.sh logs
bash scripts/deploy.sh down
# 查看包含迁移在内的所有日志
docker compose --env-file deploy/.env -f compose.prod.yaml logs --tail 200
# 重启应用（不执行迁移；升级请使用 up）
docker compose --env-file deploy/.env -f compose.prod.yaml restart api worker web
```

502 时先检查 API 健康和迁移日志；SSE 延迟时检查每层入口是否关闭缓冲；worker 重启或任务不消费时检查独占锁、模型配置和出站网络；凭据解密失败时核对原 `CREDENTIAL_KEY`。应用库若需要从 SQLite 切换 PostgreSQL，现有 checkpoint、文件共享和可选依赖也要一并规划，本方案不自动切换数据库或启用 Celery。
