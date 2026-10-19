# 故障排查与固定策略

业务入口始终为 `python3 <skill-root>/scripts/pmcp.py`，显式安装器为 `python3 <skill-root>/scripts/install_runtime.py`；`<skill-root>` 替换为实际 skill 安装目录。内部依赖 `mcporter`，包名、版本错误和兼容状态路径如实保留，不通过改名消除依赖或权限限制。

| 现象 | 先做什么 |
|---|---|
| 找不到运行时/安装记录不匹配 | 取得下载许可后显式运行安装器，不改记录、不用全局 CLI 或浮动 npx |
| Node/npm 缺失或发生变化 | 检查现有 PATH 前提，停止并报告；不能通过 skill 参数选另一套工具链或升级系统 Node。已有安装需要更新时须明确许可 |
| 没有兼容候选/依赖 EBADENGINE | 根包匹配不证明依赖满足；不 force、不忽略 engines、不升级 Node、不指定旧版本绕过 |
| 官方 registry 不可达 | 固定官方 HTTPS 源，不读 npm 配置切镜像，不暴露 registry 或环境覆盖；报告网络限制，不绕过 TLS |
| --check 未显示新候选 | 已有安装默认离线复用；明确 --update --check 才重新选择。不会安装/写运行时，但可能读官方元数据 |
| 有 stage/backup 遗留 | 不删未知目录；核对确切绝对路径、无人使用及用户许可后处理，保留可回退副本 |
| 配置被拒绝 | 严格 JSON，根 key 仅 mcpServers/imports，imports 为 []；每个服务显式 ephemeral，无 refresh/tokenCacheDir |
| Profile is busy | 固定账号 profile 正在使用，锁内部最多等 30 秒；不换目录/账号、复制凭据或改环境绕过 |
| 新命令进程看不到授权 | 比较机器、OS 账号、skill 入口、运行时版本。状态来自真实 OS home（POSIX pwd / Windows 系统 profile），环境 HOME/USERPROFILE 不切换身份；旧自选目录不导入 |
| 旧 vault JSON 损坏 | 停止，保留受保护副本；非原子写入中断可能损坏。入口不自动重置/修复，恢复/删除由用户决定；重新授权仍需现代门槛 |
| 旧版 auth 被拒绝 | auth 固定无自动浏览器且只支持 >=0.15。无接受旧风险的开关；已有合法 token 的普通操作可用不代表可重新授权，不升级 Node |
| tools --query 没匹配 | 字面、不区分大小写子串，不是正则；空列表不触发登录 |
| 工具不存在/参数错误 | 精确 tools/schema 重新发现，不猜名字、字段、fallback 或拼写纠正 |
| schema 无 annotations/title/_meta | >=0.12 上游映射省略元数据；仍可读 input/output schema，不假定原始 Tool 完整或 readOnlyHint 存在 |
| 需要授权/401 | 分清匿名、静态 header、OAuth；确认服务/账号/许可后单独 auth。旧路径 AT 过期不隐式刷新，旧 auth 门槛不能绕过 |
| 授权未自动打开浏览器 | 这是固定策略，不是故障。私有终端/受控通道处理 URL/回调；不把 code/state/token 贴模型，不承诺免交互或自动回传 |
| stdio 找不到配置/命令 | 私有 HOME 影响子进程；业务 command、脚本、cwd 使用审核过的绝对路径与必要 env，不覆盖隔离变量，不自动下载服务 |
| 超时/断连/非完整 JSON | 普通 MCP timeout 60 秒、父进程总上限 65 秒；auth/logout 父进程上限 605 秒，后端可能更早结束。结果未知，本地结束不保证远端取消，不重放副作用请求 |
| MCP isError=true / 退出 2 | 有 MCP 结果时核对部分效果；用法错误也可能退出 2，结合 stdout/stderr 区分 |
| Windows 权限失败 | 管理员本机预设受保护 ACL，入口只检查，不擅自改 ACL/提权，不宣称完整平台验收 |

固定入口不提供状态路径、Node/npm、registry、版本、超时或浏览器模式选择，也不接受部署环境覆盖。配置位置为真实 OS home 下 `.portable-mcp/config/mcporter.json`；内部目录属于实现细节，不让用户挑选。不通过直接 native CLI 或复制 token 绕过。

失败可能报告 `PMCP_ENTRY_FAILED` 或结构化 bridge 代码；读取脱敏诊断，不把 token、callback URL、完整配置/日志贴进对话。

## 不提供的能力

- 不是宿主原生工具注册器，不保证宿主一定按 description 触发。
- 不是业务授权白名单、沙箱或多租户安全边界；shell 调用者仍可能绕过入口。
- 仅 ephemeral；不支持 keepalive/daemon、connect/close/@session/serve/generate、后台订阅或 native 透传。不承诺持久会话或后台所有权管理。
- 不保证服务输出可信、行为稳定、exactly-once、效果可撤销或真实过期刷新已验收。
- 文件 vault 明文；OS 锁仅串行化合作入口，不修复旧回调漏洞、旧非原子写入或同权限恶意进程。

## 清理与验收

每条命令关闭本次连接，不保留可 close 的后台会话。检查残留只针对自己操作的 PID、启动时间、argv 和固定 profile，不 broad kill node。删除前核对绝对路径和保留要求。关闭连接、logout 本地清理、服务端撤权各自获许可，不保证取消已发起远端任务。

源码审阅、离线 doctor、宿主集成、真实 OAuth、跨进程持久性、过期刷新和业务调用分别验证。宿主权限或授权网关拦截时保留原始错误，不通过临时链接、改名或复制入口绕过。
