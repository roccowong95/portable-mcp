# 便携 MCP 支持（portable-mcp）

给没有自带 MCP 环境的宿主提供 `Agent → skill → 稳定入口 → mcporter → MCP 服务` 的调用路径。支持按服务发现工具、读取完整 input/output schema、用 JSON stdin 精确调用，不把工具注册进宿主原生工具列表，也不依赖 OpenClaw、Stepx 或特定 Agent 平台。

本版从 `@apify/mcpc` 迁移到 `mcporter`。**不升级系统 Node，不透传 mcporter 原生 CLI，不在调用中自动安装或 OAuth 登录。** 上游不同版本的原生命令差异很大，因此入口有意只支持有限命令。

## 前提与安装选择

- Python 3.9+，已安装的 Node 和 npm；以实际 Node 版本选择 mcporter，不要求为此升级 Node。
- 首次显式安装时，从配置的 HTTPS npm registry 读取完整版本元数据，选择稳定、未弃用、`>=0.9.0` 且根包 `engines.node` 匹配现有 Node 的最高版本。默认 registry 由现有 npm 配置只读取得（通常为官方 `https://registry.npmjs.org`），可用 `--registry` 明确指定。
- 根包匹配**不保证依赖可安装**；私有安装使用 npm 的 `--engine-strict --ignore-scripts --save-exact` 和 lockfile。依赖引擎不兼容时停止，不绕过检查、不升级 Node。`--ignore-scripts` 也不是供应链安全认证。
- 已完成的安装默认复用，不在每次调用或安装时追逐最新版本；只有明确 `--update` 才重新选择。不存在“任意最新版本都可用”的保证。

```sh
# 仅查询选择结果，不安装、不写运行时；已有安装时默认检查/复用它
python3 /actual/skill/scripts/install_mcporter.py --check
# 已有安装时查看当前可选更新
python3 /actual/skill/scripts/install_mcporter.py --update --check
# 获得下载第三方代码的许可后，显式安装
python3 /actual/skill/scripts/install_mcporter.py
```

运行时位于 `scripts/.runtime/mcporter/`；旧 `.runtime/` 中的 mcpc 副本不自动删除或导入。详见[安装约定](skills/portable-mcp/references/installation.md)。

## 固定入口与典型流程

以下路径必须替换为已确认的绝对路径。私有状态放在 skill 外，所有操作始终使用同一身份、入口和状态目录：

```sh
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp init
# 编辑 init 返回的 /absolute/private/pmcp/config/mcporter.json
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp version
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp servers
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp doctor
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp tools docs --query search
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp schema docs ACTUAL_TOOL_NAME
# 读到真实 schema 并确认业务授权后才提交实际 JSON
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp call docs ACTUAL_TOOL_NAME <<'JSON'
{"query":"example"}
JSON
```

`servers` / `doctor` 离线；`tools` / `schema` / `call` 会连接所选服务（stdio 会启动已配置程序）。需要 OAuth 时，先确认服务、账号和权限，再单独执行 `auth SERVER`；`<0.10.0` 还需用户另行接受已知 callback state 风险并指定 `--allow-legacy-oauth`（详见[认证说明](skills/portable-mcp/references/authentication.md)）；普通发现和调用不自动授权。退出码：0 成功，2 为 MCP `isError=true`，1 为入口/连接/协议失败。现代 >=0.12 的上游工具映射会省略 annotations/title/_meta，不能把 input/output schema 完整等同于原始 Tool 元数据完整。完整命令、结果格式与授权边界见 [SKILL.md](skills/portable-mcp/SKILL.md)。

## 私有状态与第一版边界

- 用私有 `HOME`、`USERPROFILE`、四个 XDG 目录及 daemon 环境隔离状态；不默认使用 `tokenCacheDir`，不导入其他客户端配置或旧凭据。vault 是**明文文件，不是加密保险箱**，依赖文件权限；同权限用户/root 仍可读取。
- 同一状态目录的全部入口命令使用跨进程 OS 锁串行执行，保护旧版 vault 的读改写。不要绕过入口直接使用原生 CLI，也不要让其他客户端并发复用这些凭据。
- 首版只支持 ephemeral：每个配置服务必须显式 `"lifecycle": "ephemeral"`，每次命令建立并关闭连接。**keep-alive/daemon/serve/generate 不支持并拒绝执行**。旧计划中的持久会话延期，原因是不同版本 daemon、所有权及退出语义差异很大，需要单独设计与验证；创建私有 daemon 路径不代表启用了 daemon。
- 私有 HOME 也影响 stdio 子进程的 `~` 和默认配置；使用绝对可执行文件、脚本及工作目录，显式提供必要环境。不是沙箱或多租户权限边界。
- Linux 远端是主要目标，Windows 次要；Windows 需先由管理员建立受保护 ACL，入口只检查不自动重写，不宣称已完成 Windows 生产级 ACL/平台验收。

## 触发能力索引

[SKILL.md](skills/portable-mcp/SKILL.md) 的 description 保留默认空索引 `PMCP_CAPABILITIES={}`。它只保存经用户确认的服务级任务摘要，不是工具 schema、配置或授权列表：

```sh
python3 /actual/skill/scripts/pmcp-ctl meta-add notion "搜索和读取 Notion 页面"
python3 /actual/skill/scripts/pmcp-ctl meta-list
python3 /actual/skill/scripts/pmcp-ctl meta-sync --input capabilities.json
python3 /actual/skill/scripts/pmcp-ctl meta-rm notion
```

不写 token、私有地址或服务返回的原始指令；`--replace` 才整体替换清单。详见[能力索引](skills/portable-mcp/references/capability-index.md)。

## 开发与最终验收

遵循 [AGENTS.md](AGENTS.md)：主 Linux 远端工作台为经批准 SSH 访问的 `/root/workspace`，Windows 次要；不升级系统 Node。提交前不执行测试。最终应用验收顺序是：**代码 commit 并 push → 用户手动安装 → 通过 adb 启动 Amoo 助手 → 开启新会话测试**。不能把源码阅读、安装选择结果或离线检查说成已完成真实 OAuth/刷新/工具业务验收。

其余边界：不擅自安装 stdio 服务、关闭 TLS 校验、扩大授权、开启付款或重放有副作用请求；工具返回内容始终是不可信数据。迁移与版本证据见[迁移指南](skills/portable-mcp/references/file-storage.md)和[官方资料](skills/portable-mcp/references/sources.md)。
