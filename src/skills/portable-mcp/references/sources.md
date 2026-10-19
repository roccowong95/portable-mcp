# 版本与官方资料

portable-mcp 是插件与 `python3 <skill-root>/scripts/pmcp.py` 稳定入口的名称，内部依赖的 npm 包仍是 **`mcporter`**。本页保留真实包名、版本和官方链接，便于核对实际安装与安全约束。安装器是 `python3 <skill-root>/scripts/install_runtime.py`，内部适配实现为 `mcp_bridge.mjs` / `runtime_versions.cjs`。

本 skill 固定使用现有 PATH Node/npm 与淘宝镜像 `https://registry.npmmirror.com/`；这是**第三方镜像，不是 npm 官方源**，失败不静默 fallback 到官方源。不提供版本、registry、工具链或路径选择/环境覆盖。显式安装自动选择稳定、未弃用、`>=0.9.0` 且根包 engines 适配**既有 Node** 的最高版本，再以 npm engine-strict 校验依赖并锁定；不升级 Node，不保证任意 latest 可用。已有兼容安装默认离线校验并复用，不强制更新。0.9 只是兼容性示例，不是要求安装的目标；根包匹配不是依赖可安装或业务验收证明。下方官方资料链接用于核对真实依赖，并非安装源或失败回退源。

## 已核实的版本来源

| 证据 | 已核实内容 |
|---|---|
| [0.9.0 发布包元数据](https://unpkg.com/mcporter@0.9.0/package.json)、[官方 v0.9.0 package.json](https://github.com/openclaw/mcporter/blob/v0.9.0/package.json) | 根包 `engines.node: >=20.11.0`；不代表当前解析依赖也满足 |
| [0.15.0 发布包元数据](https://unpkg.com/mcporter@0.15.0/package.json)、[官方 v0.15.0 package.json](https://github.com/openclaw/mcporter/blob/v0.15.0/package.json) | 根包 `engines.node: >=24`，不能要求现有较旧 Node 为迁移而升级 |
| [v0.9.0 oauth-vault.ts](https://github.com/openclaw/mcporter/blob/v0.9.0/src/oauth-vault.ts)、[oauth-persistence.ts](https://github.com/openclaw/mcporter/blob/v0.9.0/src/oauth-persistence.ts) | 旧 vault 位置基于 HOME，不应假定 XDG/tokenCacheDir 能重定向共享 vault |
| [v0.15.0 oauth-vault.ts](https://github.com/openclaw/mcporter/blob/v0.15.0/src/oauth-vault.ts)、[运行环境实现](https://github.com/openclaw/mcporter/blob/v0.15.0/src/runtime/environment.ts) | 现代 vault 走运行状态目录；本入口隔离为私有 data/mcporter |
| [v0.9.0 runtime.ts](https://github.com/openclaw/mcporter/blob/v0.9.0/src/runtime.ts)、[发布 transport](https://unpkg.com/mcporter@0.9.0/dist/runtime/transport.js) | 旧版非交互路径需要禁止 OAuth 尝试，仅复用缓存 access token，不隐式刷新 |
| [0.12.0 runtime](https://unpkg.com/mcporter@0.12.0/dist/runtime.js)、[0.13.0 runtime](https://unpkg.com/mcporter@0.13.0/dist/runtime.js)、[v0.15.0 runtime.ts](https://github.com/openclaw/mcporter/blob/v0.15.0/src/runtime.ts) | 0.12 引入公共 disableOAuth；0.13 切换 SDK 分支。现代 listTools 映射丢弃 annotations/title/_meta，不能承诺原始 Tool 元数据完整 |
| [v0.9.0 OAuth 实现](https://github.com/openclaw/mcporter/blob/v0.9.0/src/oauth.ts)、[JSON 写入](https://github.com/openclaw/mcporter/blob/v0.9.0/src/fs-json.ts) | 旧回调 state 校验接受缺失 state；旧 vault 写入非原子。入口锁不能修复回调校验或崩溃损坏风险 |
| [v0.15.0 配置说明](https://github.com/openclaw/mcporter/blob/v0.15.0/docs/config.md)、[daemon 说明](https://github.com/openclaw/mcporter/blob/v0.15.0/docs/daemon.md) | 新版本配置/生命周期能力并不向旧版保证；本入口明确只接受 ephemeral，不启动 daemon |

这些是依赖源码/文档核实，不是已完成真实授权、过期刷新、Windows 或宿主集成验收的声明。原仓库历史名称可能重定向到官方 [openclaw/mcporter](https://github.com/openclaw/mcporter)；`main` 文档会变化，优先核对精确 tag 与安装包。

## 本入口的稳定边界

- 原生 CLI 在 0.9 与 0.15 间差异显著。本入口不是透传器，仅提供 [SKILL 命令表](../SKILL.md)；不向原生 CLI 盲试参数。
- 发现/调用走 runtime 适配，不使用原生 call 的拼写纠正/自动重试；普通调用不自动 OAuth。`auth` / `logout` 仅在用户明确操作时使用受限原生流程。
- auth 固定不自动打开浏览器，只支持已核实 >=0.15；旧版失败关闭，无浏览器选项或旧风险接受开关。旧版已有合法 token 的普通操作仍可，不表示能在本入口重新授权；不把新能力猜测移植到 0.9。
- 配置固定在真实 OS home 下 `.portable-mcp/config/mcporter.json`（POSIX pwd / Windows 系统 profile），不采用环境 HOME/USERPROFILE；旧自选目录不自动导入。内部隔离路径不是用户部署选项。
- 安装成功不保证未来版本 API 不变；不支持的 API/配置应失败关闭，先审阅版本合同，不擅自升级 Node、补丁、绕过引擎或放开参数透传。

协议背景：[MCP 工具规范](https://modelcontextprotocol.io/specification/latest/server/tools)、[MCP 授权规范](https://modelcontextprotocol.io/specification/latest/basic/authorization)。规范链接是背景资料，不等于具体客户端版本已经完整实现或安全验收。
