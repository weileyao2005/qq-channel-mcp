# Security Policy

## 数据与隐私 / Data & Privacy

- 本工具在本地运行，所有数据（帖子缓存、登录凭证）只保存在本机
- 登录凭证 `config.json` 包含 QQ 登录态，**请勿提交到版本库或分享给他人**
- `feeds.db` 含频道内容，同样不应公开

## 凭证处理 / Credential Handling

- `config.json` 已在 `.gitignore` 中排除
- 发现凭证泄露请立即在 QQ 安全中心下线会话并更换凭证
- 不要在多台设备间共享同一份 cookie

## 操作风险 / Operational Risks

- 默认只读（浏览、搜索、统计）
- 写操作（评论、发帖、点赞）需要显式指令才会执行
- 自动化操作可能触发平台风控，账号风险自负
- 高频请求可能被 WAF 拦截（403/501），建议请求间隔 ≥250ms

## 报告漏洞 / Reporting

发现安全问题请通过 GitHub Issues 或私信作者，不要在公开渠道披露可利用细节。

## 合规 / Compliance

本工具仅供个人学习与自动化研究。请遵守 QQ 频道社区规范，勿用于刷量、骚扰、数据倒卖等用途。
