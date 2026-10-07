# 源笺安全政策

## 支持范围

当前维护最新的源笺 `0.1.x` 预览版本。旧预览版本请先备份并升级；上游版本号不是源笺的维护承诺。

## 报告漏洞

请使用本仓库的 [GitHub 私密漏洞报告入口](https://github.com/Liu-Ice-cream/yuanjian/security/advisories/new)。该入口需在公开仓库启用私密漏洞报告后使用；若未显示入口，请仅在普通 Issue 中请求开启私密联系渠道，不要公开漏洞细节、访问令牌、实例地址或研究数据。

报告中请说明源笺版本、安装方式、影响范围和最小复现步骤。源笺新增功能的问题由本仓库维护者处理；确认涉及上游后再协调上游，不使用上游维护者的邮箱接收源笺报告。

## 数据与部署

Windows 本地启动器与默认 Compose 仅监听本机。将实例开放到网络前，需自行配置 HTTPS、访问控制与可信来源，详见 [安装说明](docs/installation.md)。Windows 开发服务器不用于公网部署。

`.env`、`local_settings.py`、`data/`、`docker-data/` 含凭据或私人资料，不应提交 Git、附在 Issue 或上传诊断附件。Crossref DOI 查询发送 DOI，不发送研究卡片、笔记或摘录。
