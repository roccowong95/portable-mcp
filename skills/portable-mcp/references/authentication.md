# OAuth 与私有凭据

## 1. 普通调用没有隐式登录

区分服务类型：匿名 HTTP/stdio 不需要 OAuth；静态 API Key/Bearer 通过受控环境和配置 headers 提供；OAuth 服务明确配置 `auth: "oauth"`。先确认服务 URL、OS 身份、目标账号和最小权限，不因 401/连接失败自动登录或扩大 scope。

`tools` / `schema` / `call` **禁止自动启动 OAuth/browser**，也不自动安装运行时或服务器。服务需要授权时停止业务请求，取得用户许可后单独使用固定入口 `auth SERVER`。不调用原生 CLI 绕过门槛，不自己抽取/维护第二套 AT/RT。

## 2. 显式 auth 与版本门槛

`pmcp` 是[固定入口](installation.md)简写；下面仅展示接口，不是立即执行的授权指令：

```sh
# 默认操作 timeout 为 60000ms；登录需更长等待可显式设置（子命令前）
pmcp --timeout 300000 auth oauth-service
# 需要清理/重建认证状态时先确认，不把 reset 当常规重试
pmcp --timeout 300000 auth oauth-service --reset
# 仅已核实的 mcporter >=0.15.0 路径开放；旧版失败关闭
pmcp --timeout 300000 auth oauth-service --no-browser
```

auth 会访问网络、可能打开浏览器、写入私有 vault；允许刷新或重新授权。`--reset` 可能丢失本地认证状态，不自动执行。`--no-browser` 是禁止自动开浏览器，不等于免交互授权、离线认证或自动回传 code；0.9 的 CLI 不能凭新版文档假设兼容，即使旧文档出现其他 browser 参数，本入口仍拒绝 <0.15 的该选项。

### 0.9 交互授权的已知风险门槛

`<0.10.0` 的原生 OAuth 回调存在已核实缺陷：state 比较要求 expectedState 和 receivedState 同时存在，因此缺失 receivedState 可绕过该比较。本入口**没有补丁修复该漏洞**，私有目录/OS 锁也不能修复它。该版本 `auth`（包括 `--reset`）默认拒绝；只有用户在得知风险后单独明确接受，才加 `--allow-legacy-oauth`：

```sh
# 仅在用户另行接受上述旧回调风险后；不是默认/自动步骤
pmcp --timeout 300000 auth oauth-service --allow-legacy-oauth
```

该门槛不影响匿名/header 或已有缓存 token 的普通工具操作。可在不升级既有 Node 的前提下评估兼容的现代版；没有安全可接受的授权路径就停止，不静默跳过门槛、自动修补或升级 Node。

不要编造本入口不支持的 `--code`、`vault set`、config login、token import 或新认证扩展。需要 scope、固定 client/redirect 配置时，先核对实际安装版本的官方文档和服务要求；0.15 的新字段不向 0.9 保证兼容。

## 3. 普通请求中的 token 使用

- **0.9–0.11 旧 API 路径**：只将已有缓存 access token 注入连接，不启动 OAuth、不隐式 refresh。token 缺失/过期后可能收到未授权，必须显式 `auth SERVER` 由该版本的原生授权流程刷新或重新授权。
- **>=0.12 现代 API 路径**：使用已核实的 `disableOAuth` 等运行时开关，禁止发现/调用自动发起 OAuth。缓存 token 和刷新细节随版本/SDK 变化；本 skill 不承诺普通调用能够自动刷新，也不把现代认证扩展当成旧版能力。
- 静态 headers 不会因为禁用 OAuth 自动清除；确认实际账号/密钥来源，不混合不明 token 与 profile。token 有效不等于有当前业务权限。

auth 成功、发现成功、新进程持久性、真实过期刷新是不同验收项，不能互相代替。refresh token 失效/撤销可能需要重新授权；token 更新也不等于服务端实施了轮换。

## 4. 无桌面/远程 callback

浏览器在用户电脑而客户端在远端时，浏览器中的 localhost 指用户电脑。先确认版本支持的 redirect URI 和实际 loopback 端口；管理员可在许可下配置只绑定本机的 SSH 转发，不公开 callback 端口，结束后关闭。

若所选版本提供私有终端/stdin 回调流程，保持原 auth 进程存活，按该版本流程操作，不重放旧 code、不把 callback URL 交给模型。**含 code/state、PKCE verifier、access/refresh token 的完整 URL、日志或 JSON 不进入聊天、argv、skill 或示例。** 无浏览器授权 URL也是敏感运维输出，仅通过受控通道交给用户；不保证它适合公开。

本版不是通用 callback 校验器；不能把旧 mcpc 的安全结论直接套给 mcporter，也不能因为更换包名就宣称 OAuth 已安全验收。真实授权前核对所选版本的回调、账号、redirect 和 scope 合同，见[官方来源](sources.md)。

## 5. vault、隔离与锁

固定入口始终设置私有 HOME/USERPROFILE、XDG config/data/cache/state 和 daemon 环境，配置根 key 仅 mcpServers/imports，保持 `imports: []`，每个服务显式 lifecycle ephemeral；auth 也先校验，不读取默认其他客户端、不改写配置。无 `tokenCacheDir`；默认 vault：

- 旧版 0.9 等：`<private-state>/home/.mcporter/credentials.json`。
- 现代版 0.15 已核实：`<private-state>/data/mcporter/credentials.json`。

旧 0.9 vault 写入非原子，崩溃/中断可能留下损坏 JSON；入口遇到损坏失败关闭，不自动重置、修复或伪造凭据。锁只处理合作进程串行化，不保证写入抗崩溃。保留受保护副本，恢复/删除/重新授权由用户决定。

vault **明文、不加密**；放在 skill 外并保护权限，不提交、打包、打印或传模型。POSIX 私有目录/文件；Windows 需预先受保护 ACL，入口只检查，不承诺完整生产验收。同权限/root、恶意 stdio 子进程或泄露备份仍是风险。

同一私有状态目录的全部入口命令用 OS 锁串行执行，覆盖旧 vault 读改写和显式授权。不要直接跑 native CLI，也不要让其他客户端并发共享这些凭据；此锁只约束合作入口，不是跨客户端万能锁。不为绕过 busy 错误换入口/复制 token。

## 6. logout、迁移与撤权

```sh
pmcp logout oauth-service
```

logout 是经确认的本地清理，具体清理范围依 mcporter 版本；不等于撤销远端 grant，也不保证已运行任务取消。服务端撤权在服务账号设置中按实际流程执行，另获确认。匿名/静态 key 服务的 logout 不会替你撤销 API Key。

旧 mcpc/keyring/其他客户端凭据不自动导入，跨机器/跨版本也不复制 token 作为默认迁移；按[迁移指南](file-storage.md)重新授权。首版无后台会话/keepalive，不需要也不提供 `close @session`；结束连接不是删除凭据或撤权。
