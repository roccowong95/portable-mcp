# 故障排查与真实边界

| 现象 | 先做什么 |
|---|---|
| 找不到运行时/安装记录不匹配 | 使用固定 Python 入口；取得下载许可后显式运行安装器，不改 marker、不浮动 npx |
| Node/npm 缺失或版本变化 | 核对既有绝对路径；安装器 --node / --npm-cli，入口 --node。显式 --update 重新校验，不升级系统 Node |
| 没有兼容候选/依赖 EBADENGINE | 根包匹配不代表依赖满足。停止并报告，不 --force、不忽略 engines、不自动装新版 Node |
| --check 没显示最新候选 | 已有安装时默认离线复用；明确 --update --check 才重新选择。它不安装、不写运行时，但可能读 registry |
| .runtime 中有 stage/backup | 不删未知目录；核对确切绝对路径、无人使用及用户许可后处理，保留可回退旧副本 |
| 配置被拒绝 | 严格 JSON，根 key 仅 mcpServers/imports，imports 必须 []；每个服务显式 lifecycle: "ephemeral"，不加 refresh/tokenCacheDir |
| Profile is busy | 同一私有目录正在使用；等待或调整 --lock-timeout，不绕过锁、换客户端或复制凭据 |
| 新 SSH/exec 看不到授权 | 比较机器、OS 身份、入口、私有状态绝对路径、实际 mcporter 版本与 vault 路径；不打印 token、不自动复制旧 vault |
| 旧 vault JSON 损坏 | 停止；可能是非原子写入中断。入口不自动重置/修复；保留受保护副本，由用户决定恢复或显式重新授权 |
| 0.9 auth 被安全门槛拒绝 | 旧 callback state 校验有已知缺陷。解释风险，只有用户另行接受后才 --allow-legacy-oauth；不静默加 flag |
| tools --query 没匹配 | 是字面子串，不是正则。空列表不是登录失败，不自动 OAuth |
| 工具不存在/参数错误 | 精确 tools / schema 重新发现，不猜名字、字段、fallback 或拼写纠正 |
| schema 无 annotations/title/_meta | >=0.12 上游 listTools 映射丢弃元数据；input/output schema 仍可读取，不假定原始 Tool 完整或 readOnlyHint 存在 |
| 需要授权/401 | 分清匿名、静态 header、OAuth；确认服务/账号/许可后单独 auth。旧路径缓存 AT 过期不隐式刷新 |
| --no-browser 被拒绝 | 只开放已核实 >=0.15；不猜旧参数，不升级 Node 迁就参数，不把免开浏览器当免交互 |
| stdio 找不到配置/命令 | 私有 HOME 会影响子进程；使用已安装、已审核程序的绝对路径、cwd 和明确 env，不自动下载服务器 |
| 断连/超时/非完整 JSON | 结果未知；本地超时不保证远端取消，不重放可能有副作用的请求 |
| MCP isError=true / 退出 2 | 有 MCP 错误结果时按业务判断部分效果；argparse 用法错误也可能退出 2，结合 stdout/stderr 区分 |
| Windows 权限检查失败 | 由管理员在本机预设受保护 ACL；不擅自改 ACL/提权，不承诺完整生产验证 |

入口失败可能报告 `PMCP_ENTRY_FAILED` 或结构化 bridge 代码，先处理固定诊断；不要为取得细节把私有 token、callback URL、完整配置或日志贴进对话。

## 不提供的能力

- 不是宿主原生工具注册器，不保证宿主一定按 description 触发 skill。
- 不是业务授权白名单、沙箱或多租户安全边界；有 shell 权限的调用者仍能绕过入口。
- 不启动 keepalive/daemon，不提供 connect/close/@session/serve/generate 或任意原生参数透传。旧持久会话计划延期，需独立解决版本差异、后台所有权与退出语义。
- 不保证第三方服务输出可信、行为稳定、exactly-once、副作用可撤销或真实过期刷新已验收。
- 文件 vault 是明文；OS 锁只串行化合作入口，不修复旧回调 state 漏洞、旧 vault 非原子写入或恶意同权限进程。

## 清理与最终验收

本版命令结束会关闭本次连接，不保留可 `close` 的后台会话。超时后如需检查残留，只检查自己操作的 PID、启动时间、完整 argv 和独立目录；不 broad kill node，不清理他人进程。删除前核对绝对路径与保留要求。结束连接、`logout` 本地清理和服务端撤权是不同操作，均不保证已发起远端任务取消。

遵循[仓库要求](../../../AGENTS.md)：主 Linux 远端 `/root/workspace`，Windows 次要。**commit + push → 用户手动安装 → adb 启动 Amoo 助手 → 开启新会话测试**。提交前不执行测试。安装/源码审阅、离线 doctor、真实授权、跨进程持久性、过期刷新、低风险工具调用分别验收，不互相代替。
