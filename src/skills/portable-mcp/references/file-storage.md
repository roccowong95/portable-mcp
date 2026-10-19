# 私有存储与旧状态边界

portable-mcp 的服务配置和凭据放在 skill 外的固定私有状态中，业务统一通过 `python3 <skill-root>/scripts/pmcp.py` 访问。内部使用真实 npm 包 `mcporter` 的原生文件 vault，不修改第三方文件后端，不自动导入其他客户端配置或凭据。

## 固定新布局

真实 OS home 来自 POSIX `pwd.getpwuid` 或 Windows 系统 profile，不采用调用环境 HOME/USERPROFILE。状态根固定为 **`.pmcp`**，唯一配置为 **`.pmcp/config/mcp.json`**；内部 HOME/USERPROFILE、XDG config/data/cache/state 和 daemon 路径另行隔离，无用户路径/环境覆盖。

| 内容 | 固定位置 |
|---|---|
| 私有运行时（本次不移动） | `<skill-root>/scripts/.runtime/mcporter/` |
| 唯一服务配置 | `<真实home>/.pmcp/config/mcp.json` |
| 旧 0.9 等忽略 XDG 的 vault | `<真实home>/.pmcp/home/.mcporter/credentials.json` |
| 已核实 0.15 XDG vault | `<真实home>/.pmcp/data/mcporter/credentials.json` |

本次先调整用户状态与配置位置；运行时及上游内部 vault 命名保持原样，不宣称所有文件名已整理。0.9 只是兼容性示例，不要求安装。vault 位置随版本不同，不假定升级后读取旧文件或凭据可互换。不配置 tokenCacheDir，不使用真实 home 的默认依赖 vault。

## 不迁移、不复制、不触碰旧状态

**不自动导入、迁移或复制任何旧状态/凭据；既有 `.portable-mcp` 完全保持原样。** 新部署必须显式 `init`，再按用户批准的 URL、已审核 command/args、业务环境引用重新执行 `config-add`。不能扫描、复制或整份导入旧客户端配置，也不能因新布局下没有 token 就复制旧 vault。旧目录是否保留、备份、删除及旧授权是否撤销，由用户另行决定；本次不执行清理。

1. 确认当前机器、OS 账号及旧使用者，不批量终止进程，不覆盖旧运行时、keyring 或状态。
2. 按[安装约定](installation.md)只读检查现有环境；缺少运行时时取得下载许可后显式安装，已有兼容安装离线复用。不升级系统 Node。
3. 显式 `python3 <skill-root>/scripts/pmcp.py init`；新增服务必须用[config-add](mcp-configuration.md)，不手改 JSON。同名拒绝、无替换/删除；高级字段不支持时暂停协调。命令在 profile 锁内处理私有临时配置，补 ephemeral/cwd，验证 imports 与现有条目后原子发布，不联网、不启动 stdio、不 OAuth。
4. 需要 OAuth 时重新确认账号/最小权限和用户许可，再显式 auth。现有 Node 没有兼容现代授权路径时停止，不导入 token 或升级 Node 绕过。
5. 安装、发现、schema、获准低风险调用、跨进程持久性和真实过期刷新分别验证。关闭旧连接、本地 logout、服务端撤权分别获许可，不互相替代。

## 明文、权限与锁

vault 是**明文 JSON，不加密**。目录权限不能抵抗 root/同权限进程、备份泄露、环境泄露或恶意 stdio。POSIX 要求私有所有者、目录 0700/文件 0600；Windows 管理员须预设受保护 ACL，入口只检查，不宣称完整生产验收。

OS 锁串行化固定账号状态操作，包括 config-add；`pmcp.py meta-*` 不访问账号状态，只用 skill 内索引写入锁。不直接调用原生 CLI，不手工并发编辑，不让其他客户端并发复用 vault，不换目录/环境绕过锁。配置原子发布不等于底层 vault 也已修复：旧版 vault 非原子写入，崩溃仍可损坏 JSON；入口失败关闭，不自动修复或重置。保留受保护副本，恢复/删除由用户决定。

旧回调 state 缺陷不因新目录或锁消失；显式 auth 固定不自动开浏览器，要求已核实 `mcporter >=0.15.0`，旧版失败关闭、无风险接受开关。旧版已有合法 token 的普通操作可用，不代表能重新授权；见[OAuth 与凭据](authentication.md)。

分发只带源码；排除运行时、私有状态、配置、日志、凭据和部署特有能力索引。搬动 skill 不带账号状态，不证明真实 OAuth 生命周期已验收。
