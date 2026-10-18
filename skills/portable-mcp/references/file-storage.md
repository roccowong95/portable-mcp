# 从 mcpc 迁移：不再打文件存储补丁

旧版使用 `@apify/mcpc@0.7.0`、`MCPC_HOME_DIR`、`@session` 和可选 keychain 源码补丁。本版改为 `mcporter` 原生文件 vault + 私有 HOME/XDG 隔离，**不需要也不允许把旧文件后端补丁套到新包**。旧 `install_mcpc.py`、`mcpc.py`、`force_file_store.py` 保留为失败关闭的退役提示，不再执行旧安装、连接或补丁。

## 迁移步骤

1. 确认旧部署有无正在运行的工作/会话及使用者。不要 broad kill node，不自动删除旧 `.runtime/`、keyring、状态或授权。
2. 保留旧源码/状态直至管理员明确批准处理；不要打印或复制 access token、refresh token、PKCE、client secret。迁移 skill 不迁移凭据。
3. 按[安装约定](installation.md)，用既有 Node/npm 显式安装兼容稳定 mcporter 到 `scripts/.runtime/mcporter/`。不升级系统 Node，也不覆盖旧 `.runtime/` 中的其他内容。
4. 在 skill 外新建受保护私有状态目录，用 `mcporter.py --state-dir ABS init` 生成空配置。只将经批准的服务 URL、绝对 command/args、必要 env 引用迁入该目录的 `config/mcporter.json`，保留 `"imports": []`，为每个服务明确 `"lifecycle": "ephemeral"`；根 key 仅 mcpServers/imports。不直接拷贝旧客户端全部配置。
5. 对 OAuth 服务按[显式授权](authentication.md)重新确认账号/权限并 `auth SERVER`。不自动导入旧 mcpc keyring、其他 mcporter 客户端 vault 或历史 tokenCacheDir。跨版本升级如 vault 路径改变，也不自动拷贝/宣称 token 通用；需要时重新授权。
6. 经用户安装后的新 exec/SSH 和 Amoo 新会话分别确认发现、schema 和低风险业务调用；真实过期刷新另行确认。关闭旧会话、本地 logout、服务端撤权是独立操作，分别取得许可。

## 新版凭据布局

| 分支 | 默认文件位置（由固定入口隔离） |
|---|---|
| 旧版 mcporter 0.9 等忽略 XDG 的 vault | `<private-state>/home/.mcporter/credentials.json` |
| 现代版（0.15 已核实）XDG vault | `<private-state>/data/mcporter/credentials.json` |

两者都在 skill 外的私有目录；不配置 `tokenCacheDir`，不使用真实用户 HOME 的默认 vault。路径选择取决于具体安装版本，不能仅因升级后有旧文件就假定新版本已读取它。

这些是**明文 JSON**，目录权限不是加密；不抵抗 root/同权限进程、备份泄露、环境泄露或恶意 stdio 子进程。POSIX 用私有所有者和目录 0700/文件 0600；Windows 管理员先设置受保护 ACL，入口检查而不擅自改权限，不宣称完整生产 ACL 验收。

旧 0.9 vault 写入非原子，崩溃可损坏 JSON，入口不自动修复/重置；旧 callback state 校验还存在已知缺陷，`<0.10` auth 需另行风险同意与 `--allow-legacy-oauth`，详见[认证门槛](authentication.md)。这些问题都不因迁移/私有权限/锁而消失。

入口的 OS 锁覆盖全部状态操作，尤其串行化旧版 vault 的读改写；所有客户端必须遵守同一入口，不直接调用 native CLI或并发共享凭据。分发排除运行时、状态、配置、日志、vault 和部署索引。

## 为何不继续旧方案

mcpc 的源码 SHA 绑定补丁与 mcporter 无关；文件后端本身也不能修复 OAuth 回调、刷新竞争、服务端撤权或跨进程身份绑定。旧计划的 keepalive/后台会话同样不随迁移继承：首版只提供 ephemeral，daemon/持久连接的版本差异与所有权需单独验证，见[边界与排错](troubleshooting.md)。
