# 从 mcpc 迁移：固定状态，不再打补丁

旧版使用 `@apify/mcpc@0.7.0`、自选状态、@session 和可选 keychain 补丁。本版改为 mcporter 原生文件 vault + 固定私有 HOME/XDG 隔离，**不套用旧文件后端补丁、不迁移旧凭据**。旧 install_mcpc.py、mcpc.py、force_file_store.py 仅保留失败关闭的退役提示。

## 迁移步骤

1. 确认旧部署的运行工作/会话及使用者，不 broad kill node，不自动删除旧运行时、keyring、状态或授权。
2. 保留旧源码/状态直至管理员明确批准处理。不要打印或复制 AT/RT、PKCE、client secret。迁移 skill 不迁移凭据，**旧自选状态目录也不自动搬迁到固定目录**，避免混入其他账号/部署的秘密。
3. 按[安装约定](installation.md)取得下载许可，使用现有 PATH Node/npm 显式安装；固定官方 registry，自动选兼容最高稳定版本后锁定。不提供版本/路径/工具链选择，不升级系统 Node，不覆盖旧运行时其他内容。
4. 用 `mcporter.py init` 建立 OS 账号真实 home 下固定 `.portable-mcp` 状态（POSIX pwd、Windows 系统 profile，不采用环境 HOME/USERPROFILE）。编辑返回的 `.portable-mcp/config/mcporter.json`，仅迁入批准的 URL、绝对 command/args、必要业务 env 引用；根 key 仅 mcpServers/imports，`imports: []`，每个服务显式 `"lifecycle": "ephemeral"`。不直接拷贝旧客户端全部配置。
5. OAuth 先重新确认账号/权限，再按[显式授权](authentication.md)执行 `auth SERVER`。auth 固定不自动开浏览器，只支持 >=0.15；旧版无接受风险开关。现有 Node 没有兼容现代路径则停止，不升级 Node。旧版已有合法 token 的普通操作可用不代表可重新授权；不导入旧 keyring、其他客户端 vault 或 tokenCacheDir。
6. commit + push 后由用户手动安装，再通过 adb 启动 Amoo 并开新会话测试；分别确认发现、schema、低风险调用及真实过期刷新。关闭旧会话、本地 logout、服务端撤权分别获许可，不互相替代。

## 内部凭据布局，不是部署选项

| 版本示例 | 由入口固定隔离的位置 |
|---|---|
| 旧 0.9 等忽略 XDG 的 vault | `<真实home>/.portable-mcp/home/.mcporter/credentials.json` |
| 已核实现代 0.15 XDG vault | `<真实home>/.portable-mcp/data/mcporter/credentials.json` |

0.9 只是兼容性示例，不要求安装。两种位置都由实现管理、在 skill 外，不让用户选择；不配置 tokenCacheDir、不使用真实 home 默认 mcporter vault。跨版本位置变化也不自动复制 token 或假定新版本已读取旧文件。

vault 是**明文 JSON**，权限不是加密，不抵抗 root/同权限进程、备份泄露、环境泄露或恶意 stdio。POSIX 私有所有者、目录 0700/文件 0600；Windows 管理员预设受保护 ACL，入口只检查，不宣称完整生产验收。

旧 0.9 vault 非原子写入，崩溃可损坏 JSON；入口不自动修复/重置。旧 callback state 缺陷不因目录/锁消失，auth 由固定 >=0.15 门槛失败关闭，无风险接受开关。

OS 锁串行化全部入口状态操作，不直接 native CLI，不让其他客户端并发复用 vault，不通过换目录/环境绕过锁。分发排除运行时、私有状态、配置、日志、凭据和部署索引。

## 为何不延续旧方案

旧 mcpc 的源码 SHA 绑定补丁与 mcporter 无关；文件后端不能修复 OAuth 回调、刷新竞争、撤权或跨进程身份绑定。旧 keepalive/后台会话也不随迁移继承：首版仅 ephemeral，daemon/持久连接的版本差异与所有权需单独设计验证，见[边界与排错](troubleshooting.md)。
