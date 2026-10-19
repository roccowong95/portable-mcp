# 私有存储、兼容路径与迁移

portable-mcp 的服务配置和凭据放在 skill 外的固定私有状态中，业务统一通过 `python3 <skill-root>/scripts/pmcp.py` 访问。内部使用 npm 包 `mcporter` 的原生文件 vault，不修改第三方文件后端，也不自动导入其他客户端凭据。

## 固定布局，不随产品名称移动

真实 OS home 来自 POSIX `pwd.getpwuid` 或 Windows 系统 profile，不采用调用环境 HOME/USERPROFILE。状态根固定为 `.portable-mcp`；内部 HOME/USERPROFILE、XDG config/data/cache/state 和 daemon 路径另行隔离。

以下兼容路径保留原名，不是用户部署选项：

| 内容 | 固定位置 |
|---|---|
| 私有运行时 | `<skill-root>/scripts/.runtime/mcporter/` |
| 唯一服务配置 | `<真实home>/.portable-mcp/config/mcporter.json` |
| 旧 0.9 等忽略 XDG 的 vault | `<真实home>/.portable-mcp/home/.mcporter/credentials.json` |
| 已核实 0.15 XDG vault | `<真实home>/.portable-mcp/data/mcporter/credentials.json` |

0.9 只是兼容性示例，不要求安装。vault 位置随依赖版本不同，不自动复制 token，也不假定更新后已读取旧文件。不配置 tokenCacheDir，不使用真实 home 的默认依赖 vault。内部路径保持兼容不等于保证跨版本凭据可互换。

## 明文与权限边界

vault 是**明文 JSON，不加密**。目录权限不能抵抗 root/同权限进程、备份泄露、环境泄露或恶意 stdio。POSIX 要求私有所有者、目录 0700/文件 0600；Windows 管理员须预设受保护 ACL，入口只检查，不宣称完整生产验收。

OS 锁串行化业务入口的固定账号状态操作；`pmcp.py meta-*` 不访问账号状态，只用 skill 内的索引写入锁。不直接调用原生 CLI，不让其他客户端并发复用 vault，不通过换目录/环境绕过锁。锁只约束合作入口，不能修复旧版非原子写入：崩溃仍可损坏 JSON，入口失败关闭，不自动修复或重置。保留受保护副本，恢复/删除由用户决定。

旧回调 state 缺陷不因目录或锁消失；显式 auth 固定不自动开浏览器，要求已核实 `mcporter >=0.15.0`，旧版失败关闭，没有风险接受开关。旧版已有合法 token 的普通操作可用，不代表能重新授权；见[OAuth 与凭据](authentication.md)。

## 从既有部署迁移

1. 确认旧部署的工作、连接及使用者；不批量终止 Node，不自动删除运行时、keyring、状态或授权。不因入口改名执行清理。
2. 保留旧状态，直到管理员明确批准处理。不打印或复制 AT/RT、PKCE、client secret。旧自选状态目录、其他客户端 vault 或 keyring 不自动搬迁；旧文件后端补丁不适用于本实现。
3. 按[安装约定](installation.md)检查现有环境，取得下载许可后运行 `python3 <skill-root>/scripts/install_runtime.py`。固定淘宝第三方镜像 `https://registry.npmmirror.com/`，失败不静默 fallback 官方源；自动选兼容稳定版本后锁定，已有兼容安装离线复用、不强制更新。不升级系统 Node，不覆盖其他运行时。
4. 执行 `python3 <skill-root>/scripts/pmcp.py init`，编辑返回的固定配置。只迁入获准的 URL、绝对 command/args、必要业务 env 引用；根 key 仅 `mcpServers` / `imports`，`imports: []`，每个服务显式 `"lifecycle": "ephemeral"`。不整份复制其他客户端配置。
5. OAuth 重新确认账号/最小权限后才显式授权；现有 Node 没有兼容现代授权路径时停止，不升级 Node 或导入 token 绕过门槛。安装、发现、schema、获准低风险调用、跨进程持久性及真实过期刷新分别验证。
6. 旧会话关闭、本地 logout、服务端撤权分别获许可，不互相替代。当前仅支持 ephemeral，不继承旧后台会话或跨命令订阅，见[故障排查](troubleshooting.md)。

分发只带源码；排除运行时、私有状态、配置、日志、凭据和部署特有能力索引。迁移 skill 不迁移凭据，也不证明真实 OAuth 生命周期已验收。
