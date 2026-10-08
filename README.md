# 源笺 · 个人研究资料工作台

**帮助研究者把收藏的资料转化成可复用的研究材料。**

源笺 v0.1.5 是面向个人研究者的早期预览版，基于 [linkding](https://github.com/sissbruecker/linkding) v1.47.0 开发。把论文、网页与代码资料整理成有来源的研究卡片、课题提纲和引用文件。

## 当前能做什么

- 收集论文、代码仓库、数据集、技术文章和其他网页资料，保留原始来源。
- 一键读取网页标题和简介，只补全空白字段，保留手动输入；读取失败仍能保存。
- 创建研究课题，把不同类型的资料归入同一研究目标。
- 从课题内收集资料时默认带入该课题，也可修改或取消归属。
- 通过“待整理”找回还没有研究问题或核心结论的收藏，填写后自动计入“已有研究记录”。
- 管理待阅读、阅读中、已阅读和已复用四个阶段。
- 填写结构化研究卡片：研究问题、核心结论、证据与实验、局限与注意事项、与课题的关系。
- 每份资料保存多条研究摘录，分别记录原文、个人理解和来源位置；支持编辑与可恢复移除。
- 按课题汇总、搜索摘录，并勾选当前页需要的内容导出 Markdown，包含完整摘录和原始链接。
- 将课题摘录编排到自定义主题分组，调整分组和材料顺序、跨组移动，移除后可恢复或重新加入。
- 按“课题 → 分组 → 摘录”导出 Markdown 提纲，保留完整原文、个人理解、来源位置和原始链接。
- 通过 DOI 读取论文信息，预览后只补全空白字段，支持手工修订；读取失败仍能保存。
- 收集或编辑论文信息时提醒同账号下相同 DOI 的已有资料，保留原研究记录。
- 按课题或当前提纲导出 BibTeX，同一论文只导出一次，并提示缺失信息。
- 搜索标题、标签、原笔记及研究卡片内容，并组合课题、类型、阶段筛选。
- 将当前筛选结果完整导出为 Markdown，包含研究记录与来源链接，可继续用于汇报、写作和笔记。

旧收藏直接出现在研究资料列表，可逐步整理；原有收藏库、附件、标签、HTML 导入导出与 API 继续保留。研究卡片及课题按账号隔离，旧收藏的公开分享不会开放研究记录。

## Windows 本地运行

需要 Python 3.13+、Node.js 和 npm；本机已验证 Python 3.14.5、Node.js 24。首次安装在 PowerShell 执行：

```powershell
git clone https://github.com/Liu-Ice-cream/yuanjian.git
cd yuanjian
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
.\start-local.cmd
```

访问 <http://127.0.0.1:9090/research/>。管理员用户名为 `localadmin`，随机密码保存在本机 `data/local-access.json`。初始化脚本不会重置已有账号密码。

以后双击 `start-local.cmd` 启动，双击 `stop-local.cmd` 停止，资料仍保存在 `data/`。新版本增加迁移时先停止服务、备份整个 `data/`，再运行 setup 脚本完成升级。

## Docker Compose 运行

安装 Docker（含 Compose v2）与 Python 3 后，在仓库目录执行：

```sh
python scripts/setup-compose.py
docker compose up --build -d --wait
```

访问 <http://127.0.0.1:9090/research/>。账号和随机密码见本机 `.env` 中的 `LD_SUPERUSER_NAME`、`LD_SUPERUSER_PASSWORD`。初始化保留已有 `.env`，重启保留账号与资料。容器默认仅监听本机，数据保存在 `docker-data/`，与 Windows 的 `data/` 分开。

镜像从本仓库构建，尚未提供预构建镜像。安装、升级、备份与部署范围见 [安装说明](docs/installation.md)。容器与 Windows 从零安装、重复初始化及数据保留由 CI 验收，版本结果见 [v0.1.5](docs/releases/release-v0.1.5.md)。

Windows 排障见 [本地运行说明](https://github.com/Liu-Ice-cream/yuanjian/blob/main/docs/installation.md)。启动器使用 Django 开发服务并仅监听本机，独立后台 worker 处理原有收藏任务。

账号、研究资料与配置仅保存在自己的实例中，内部开发记录不随源码分发。详见 [数据与隐私](docs/privacy.md)。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe manage.py check --settings=local_settings
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=local_settings
.\.venv\Scripts\python.exe -m pytest bookmarks/tests research/tests -n 4
npm.cmd run build
.\.venv\Scripts\python.exe scripts/check-local.py
```

`research/` 是新增的研究资料模块。原始 `bookmarks/`、`LD_*` 配置、API 路径及数据库表名保留，以兼容已有数据和客户端。产品版本为 `bookmarks/settings/base.py` 中的 `PRODUCT_VERSION`；`version.txt` 和依赖项目元数据记录上游基线版本。

GitHub Actions 会检查迁移、运行单元测试与浏览器回归；原上游容器发布任务仅允许在上游仓库运行。本版本未发布公开容器或线上服务。

## 接下来的方向

当前以个人、自托管研究资料整理为主，尚未提供 PDF 内置阅读、arXiv 自动识别、卷期页码自动补全、AI 摘要或团队协作。引用导出前应核对缺失提示与论文原文。

遇到问题，请提交 [问题反馈](https://github.com/Liu-Ice-cream/yuanjian/issues/new/choose)，附版本、系统和复现步骤，去掉密码、令牌及私人研究内容。参与开发见 [贡献指南](CONTRIBUTING.md)，漏洞报告见 [安全政策](SECURITY.md)。

先用真实课题验证整理和复用流程，再考虑 arXiv 自动识别、PDF 阅读与更细致的引用信息。AI 摘要和跨资料检索放到后续评估，第一版研究内容由用户手动记录。

版本说明见 [v0.1.5](docs/releases/release-v0.1.5.md)、[v0.1.4](docs/releases/release-v0.1.4.md)、[v0.1.3](docs/releases/release-v0.1.3.md)、[v0.1.2](docs/releases/release-v0.1.2.md)、[v0.1.1](docs/releases/release-v0.1.1.md) 和 [v0.1.0](docs/releases/release-v0.1.0.md)。

## 来源与许可证

基于 Sascha Kaspari 及贡献者开发的 linkding，基线提交 `24b5ad6cc9bde497b5d1b1e86aed5a2fb7d25c2f`。保留完整上游历史、原始 [MIT 许可证及版权声明](LICENSE.txt)，上游介绍存放在 [upstream-readme.md](docs/upstream-readme.md)。源笺的改进也使用 MIT 许可证。
