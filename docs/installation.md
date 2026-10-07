# 安装、升级与备份

源笺 v0.1.5 为个人、自托管使用的早期预览版。Windows 启动器与 Docker Compose 使用独立数据目录，不直接混用正在运行的数据库。

## Windows 本地安装

准备 Python 3.13+、Node.js 22+、npm 和 Git，确认 `python --version` 与 `npm.cmd --version` 可运行。首次安装需要网络下载依赖。

```powershell
git clone https://github.com/Liu-Ice-cream/yuanjian.git
cd yuanjian
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
.\start-local.cmd
```

访问 <http://127.0.0.1:9090/research/>。凭据见 `data/local-access.json`。安装创建 `.venv/`、`node_modules/`、`local_settings.py` 与 `data/`；重复安装保留已有账号、密码及资料。启动器同时运行网页和后台 worker，并验证队列任务执行。

停止：`stop-local.cmd`。换端口：`start-local.cmd -Port 9091`。此方式使用 Django 开发服务器，适合本机使用。

## Docker Compose 安装

准备 Docker Engine 或 Docker Desktop（Linux 容器模式）、Compose v2 与 Python 3。克隆仓库后执行：

```sh
python scripts/setup-compose.py
docker compose up --build -d --wait
```

初始化生成本机 `.env`。管理员用户名与随机密码分别为 `LD_SUPERUSER_NAME`、`LD_SUPERUSER_PASSWORD`，不要把文件发到 Issue。已有 `.env` 不会覆盖；修改该文件中的密码不会重置已建立账号，可在应用设置中改密码。

若此前自行复制过 `.env.sample`，两项管理员配置可能仍为空，首次启动前需自行填写。升级旧实例时保持原数据目录与账号设置。

访问 <http://127.0.0.1:9090/research/>。默认仅绑定 `127.0.0.1:9090`，数据挂载为 `docker-data/`。首次源码构建需要下载基础镜像、系统包与 Python/Node 依赖，未提供预构建镜像。

```sh
docker compose ps
docker compose logs --tail 100
docker compose down
docker compose up -d --wait
```

重新创建容器保留宿主机数据。本版 CI 验收默认镜像的 Linux amd64 构建和运行；未验证 ARM、Alpine、Plus 快照变体、PostgreSQL 或 OIDC 部署。

## 升级与备份

1. 停止服务：Windows 执行 `stop-local.cmd`，Docker 执行 `docker compose down`。
2. 安全复制完整数据目录：Windows 为 `data/`，Docker 为 `.env` 指定的目录（默认 `docker-data/`）。同时备份 `local_settings.py` 或 `.env`。仅导出书签 HTML 不包含完整研究记录、附件和密钥。
3. 更新代码到目标版本。Windows 重新执行 setup 脚本并启动；Docker 执行 `docker compose up --build -d --wait`。启动会运行迁移。
4. 登录检查资料、课题与导出。回退时先停止服务，再恢复与旧代码匹配的整份备份；不要只回退代码并沿用已迁移数据库。

已有 Compose 配置从 `./data` 升级时，应在 `.env` 显式保留原来的 `LD_HOST_DATA_DIR`。新安装默认目录改为 `./docker-data`，不会自动搬迁旧数据。

## 对外部署范围

默认面向本机。对外部署应配置 HTTPS 反向代理，按域名设置 `HOST_NAME` 和 `LD_CSRF_TRUSTED_ORIGINS`，并明确开放 `LD_HOST_BIND`。更多继承配置见 [Options](src/content/docs/options.md)。Windows 开发服务器不用于公网，本版未完成公网生产运维验收。

## 遇到问题

Windows 查看 `data/web.stderr.log` 与 `data/worker.stderr.log`；Docker 查看 Compose 日志。端口占用可修改启动端口或 `.env` 的 `LD_HOST_PORT`。反馈请附版本、环境及已脱敏的日志，不要附凭据、数据库或私人研究内容。
