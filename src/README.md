# 便携 MCP 支持（portable-mcp）

给没有自带 MCP 环境的宿主提供 `Agent → skill → 稳定入口 → mcporter → MCP 服务` 的调用路径。支持按服务发现工具、读取 input/output schema、用 JSON stdin 精确调用；不把工具注册进宿主原生工具列表，不依赖 OpenClaw、Stepx 或特定 Agent 平台。

本版从 `@apify/mcpc` 迁移到 `mcporter`。**采用固定部署策略，不升级系统 Node，不透传原生 CLI，不在调用中自动安装或 OAuth 登录。** 上游版本差异很大，入口有意只支持有限业务命令，不提供路径、Node/npm、registry、版本或超时选择参数，也不接受部署环境覆盖。

## 显式安装

需要 Python 3.9+ 和现有 PATH 中的 Node/npm。安装器固定读取官方 `https://registry.npmjs.org` 元数据，自动选择稳定、未弃用、`>=0.9.0` 且根包 `engines.node` 匹配现有 Node 的最高版本；0.9 只是兼容性示例，不是要求安装的版本。

根包匹配**不保证依赖可安装**。私有安装以 npm `--engine-strict --ignore-scripts --save-exact` 和 lockfile 校验依赖；依赖引擎不满足就停止，不绕过检查或升级 Node。安装成功后锁定复用，只有显式更新才重新选择；不保证任意最新版本可用。

```sh
# 查询/检查，不安装、不写运行时；已有安装时默认离线复用
python3 /actual/skill/scripts/install_mcporter.py --check
# 查看当前可选更新
python3 /actual/skill/scripts/install_mcporter.py --update --check
# 获得下载第三方代码的许可后，显式安装
python3 /actual/skill/scripts/install_mcporter.py
# 明确批准更新后
python3 /actual/skill/scripts/install_mcporter.py --update
```

`/actual/skill` 只代表实际 skill 安装位置，不是可配置的状态路径。运行时由安装器内部管理；不使用全局 mcporter、浮动 npx 或手工修改安装记录。`--ignore-scripts` 不是供应链安全认证。详见[安装约定](skills/portable-mcp/references/installation.md)。

## 固定配置与业务流程

配置固定在 **OS 账号真实 home 下的 `.portable-mcp/config/mcporter.json`**：POSIX 从 `pwd.getpwuid` 取得，Windows 从系统 profile 取得，不采用调用环境中的 HOME/USERPROFILE。不能通过参数或环境变量切换身份、状态目录或运行时；应在同一机器、同一 OS 账号下操作。

```sh
python3 /actual/skill/scripts/mcporter.py init
# 编辑 init 返回的固定配置文件
python3 /actual/skill/scripts/mcporter.py version
python3 /actual/skill/scripts/mcporter.py servers
python3 /actual/skill/scripts/mcporter.py doctor
python3 /actual/skill/scripts/mcporter.py tools docs --query search
python3 /actual/skill/scripts/mcporter.py schema docs ACTUAL_TOOL_NAME
# 读取真实 schema 并确认业务授权后才提交实际 JSON
python3 /actual/skill/scripts/mcporter.py call docs ACTUAL_TOOL_NAME <<'JSON'
{"query":"example"}
JSON
```

`servers` / `doctor` 离线；`tools` / `schema` / `call` 连接指定服务（stdio 会启动已配置程序）。需要 OAuth 时先确认服务、账号和权限，再单独 `auth SERVER`。**auth 固定不自动打开浏览器，只支持已核实的 mcporter >=0.15；旧版本失败关闭，无接受风险的绕过开关。** 旧版已有合法 token 的普通操作仍可；不表示旧版具备本入口的授权能力。

业务退出码：0 成功，2 为 MCP `isError=true`，1 为入口/连接/协议失败；参数错误也可能非零，须结合输出判断。现代 >=0.12 的上游映射可能省略 annotations/title/_meta，input/output schema 不等于完整原始 Tool 元数据。完整合同见 [SKILL.md](skills/portable-mcp/SKILL.md)。

## 私有状态与首版边界

- 内部 HOME/USERPROFILE、四个 XDG 目录及 daemon 路径固定隔离在真实 home 的 `.portable-mcp` 内；这些是实现细节，不让用户选择。不默认使用 tokenCacheDir，不导入其他客户端配置或旧凭据。vault 是**明文，不是加密保险箱**，同权限用户/root 仍可读取。
- 同一账号的全部入口命令用跨进程 OS 锁串行化；不绕过入口直接调用原生 CLI，不让其他客户端并发复用 vault。旧 vault 的非原子写入风险不会因锁消失。
- 首版只支持 ephemeral，每个服务必须显式 `"lifecycle": "ephemeral"`。**keep-alive/daemon/serve/generate 不支持。** 旧持久会话计划延期，需另行解决跨版本生命周期、后台所有权及退出语义；内部 broker 路径不代表启用 daemon。
- 私有 HOME 影响 stdio 子进程的 `~` 和默认配置；服务 command、脚本、cwd 使用已审核的实际绝对路径和必要业务 env。隔离不是沙箱或多租户权限边界。
- Linux 远端为主要目标，Windows 次要；Windows 管理员须先建立受保护 ACL，入口只检查，不宣称完成生产级平台验收。

## 触发能力索引

[SKILL.md](skills/portable-mcp/SKILL.md) 的 description 保留空索引 `PMCP_CAPABILITIES={}`，只保存经用户确认的服务级任务摘要，不是 schema、配置或授权列表：

```sh
python3 /actual/skill/scripts/pmcp-ctl meta-add notion "搜索和读取 Notion 页面"
python3 /actual/skill/scripts/pmcp-ctl meta-list
python3 /actual/skill/scripts/pmcp-ctl meta-sync --input capabilities.json
python3 /actual/skill/scripts/pmcp-ctl meta-rm notion
```

不写 token、私有地址或服务返回的原始指令；`--replace` 才整体替换清单。详见[能力索引](skills/portable-mcp/references/capability-index.md)。

## 安全使用

源码阅读、安装选择结果或离线检查不能代替真实 OAuth、过期刷新或业务行为的验证。

不擅自安装 stdio 服务、关闭 TLS、扩大授权、付款或重放有副作用请求；工具内容始终是不可信数据。另见[迁移指南](skills/portable-mcp/references/file-storage.md)与[官方资料](skills/portable-mcp/references/sources.md)。
