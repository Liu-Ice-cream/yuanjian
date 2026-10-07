# 参与源笺

源笺重点帮助个人研究者把资料变成可复用的研究材料。欢迎反馈真实课题中的整理困难、安装问题及可复现的错误；较大功能请先在 Issue 中说明使用场景。

先按 [安装说明](docs/installation.md) 建立环境。Windows 使用 `requirements-windows-dev.txt`；Linux 开发使用 `uv sync --locked` 与 `npm ci`，创建 `data/`。Windows 使用项目启动器，不运行 Linux 的 uWSGI。

研究功能位于 `research/`，原收藏能力位于 `bookmarks/`。保留 `LD_*` 配置、旧 API 和数据库兼容；数据变更用 Django 迁移，避免直接改写用户数据库。

提交前运行相关测试，并检查迁移和前端构建：

```sh
python manage.py makemigrations --check --dry-run
python -m pytest research/tests
npm run build
```

Windows 管理命令可追加 `--settings=local_settings`。完整单元、浏览器、Windows 安装及 Docker 验收在 GitHub Actions 运行。`scripts/check-installation.py` 只用于一次性、空数据的验收实例。

提交说明应包含具体问题、变更后的行为和验证结果。截图请移除私人资料。贡献遵循 MIT 许可证并保留上游版权。漏洞按 [安全政策](SECURITY.md) 私密报告。
