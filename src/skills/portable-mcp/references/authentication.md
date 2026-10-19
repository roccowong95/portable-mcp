# 显式 OAuth 与私有凭据

## 1. 普通业务调用不登录

匿名 HTTP/stdio 不需要 OAuth；静态 API Key/Bearer 通过受控业务环境与 headers 提供；OAuth 服务明确 `auth: "oauth"`。先确认服务、OS 账号、目标业务账号和最小权限，不因 401 自动登录、改账号或扩大 scope。

`tools` / `schema` / `call` **不启动 OAuth 或浏览器，不自动安装任何包**。需要授权就暂停业务请求，确认用户许可，再单独 `auth SERVER`；不调用原生 CLI 绕过，不抽取/维护第二套 AT/RT。

## 2. 固定无浏览器授权与版本门槛

以下通过[固定入口](installation.md)展示接口，不是立即执行的授权指令；`/actual/skill` 替换为实际 skill 安装目录：

```sh
python3 /actual/skill/scripts/pmcp.py auth oauth-service
# 清理/重建认证状态须另行确认，不作为普通重试
python3 /actual/skill/scripts/pmcp.py auth oauth-service --reset
```

**auth 固定不自动打开浏览器，仅支持已核实 mcporter >=0.15.0。** 用户没有浏览器模式、超时、旧版风险接受或其他认证开关；<0.15 的 auth（包括 reset）失败关闭。旧版本即使存在不同原生参数，也不允许绕过入口尝试。不升级系统 Node 迁就授权；现有 Node 无兼容现代授权路径时停止并说明限制。

auth 会联网并写入私有 vault，可刷新或重新授权；不自动开浏览器不等于免交互、离线授权或自动回传 code。内部 auth/logout 父进程上限为 605 秒（600 秒预算加 5 秒清理窗口），不向原生 CLI 传入该预算，后端可能更早结束，不保证授权等待恰好 600 秒；profile 锁等待 30 秒，不可通过参数或环境覆盖。reset 可能丢失本地状态，必须单独确认。

已核实的旧 0.9 回调 state 比较要求 expectedState 与 receivedState 同时存在，缺失 receivedState 可绕过比较。入口不补丁修复该缺陷，目录权限/锁也不能修复；固定现代门槛不提供接受风险绕过。0.9 仅是兼容性示例，不是要求安装的目标。

不要编造 code 回传、vault set、config login、token import 或新认证扩展。scope、client/redirect 字段先核对实际版本与服务合同，新文档不向旧版保证兼容。

## 3. 已有 token 与普通操作

- **0.9–0.11 旧 API 路径**：普通操作只注入已有合法缓存 access token，不启动 OAuth、不隐式 refresh。匿名/header/已有合法 token 的普通 tools/schema/call 仍可；token 缺失/过期后停止。旧版 auth 被固定门槛拒绝，没有风险接受开关。
- **>=0.12 现代 API 路径**：使用已核实 disableOAuth 等开关，禁止发现/调用自动发起 OAuth。缓存/刷新细节随版本和 SDK 变化，不承诺普通操作自动刷新；需要显式 auth 时仍要求 >=0.15。
- 静态 headers 不会因禁用 OAuth 自动清除；确认账号与密钥来源，不混合不明 token。token 有效不代表当前业务已授权。

auth 成功、发现成功、新进程持久性、真实过期刷新是独立验收项；refresh token 撤销/失效可能需重新授权，token 更新不证明服务端轮换。

## 4. 无桌面与远程 callback

不自动打开浏览器时，授权 URL 仅通过私有终端/受控通道交给用户，保持原 auth 进程存活并遵循实际版本的回调流程。若浏览器和客户端在不同机器，浏览器中的 localhost 指浏览器所在机器；先核对 redirect URI 和实际 loopback 端口，由管理员经许可安排与该回调合同匹配的私有连接，结束后关闭，不公开 callback 端口。本入口不提供远程回调转发器，也不承诺此部署一定可完成授权。

不承诺自动 code 回传，不重放旧 code，不把 callback URL 交给模型。**含 code/state、PKCE verifier、access/refresh token 的 URL、日志或 JSON 不进入聊天、argv、skill 或示例。** 授权 URL 本身也可能敏感，不适合公开。

本入口不是通用 callback 校验器，不能把其他客户端的安全结论套给底层依赖，也不因产品或入口命名变化宣称 OAuth 已验收。真实授权前核对版本、回调、账号、redirect 和 scope，见[官方来源](sources.md)。

## 5. 固定状态、vault 与锁

状态根固定在 OS 账号真实 home 的 `.portable-mcp`；POSIX 取 pwd 用户目录，Windows 取系统 profile，不采用环境 HOME/USERPROFILE，不迁移旧自选目录。内部再设置私有 HOME/USERPROFILE、四个 XDG 目录和 daemon 路径。配置固定 `config/mcporter.json`，根 key 仅 mcpServers/imports，imports 为 []，每个服务显式 ephemeral；auth 也先校验，不读其他客户端、不改写配置，无 tokenCacheDir。

用于解释版本差异的内部 vault 位置，不是可选择路径：

- 旧 0.9 等：`<真实home>/.portable-mcp/home/.mcporter/credentials.json`。
- 已核实现代 0.15：`<真实home>/.portable-mcp/data/mcporter/credentials.json`。

旧 vault 非原子写入，崩溃/中断可损坏 JSON；入口失败关闭，不自动重置、修复或伪造凭据。保留受保护副本，恢复/删除由用户决定；重新授权仍受现代门槛约束。

vault **明文不加密**，不提交、打包、打印或传模型。POSIX 私有权限；Windows 管理员预建受保护 ACL，入口只检查，不宣称完整生产验收。同权限/root、恶意 stdio 或泄露备份仍有风险。

固定 profile 的全部入口命令由 OS 锁串行化，不直接 native CLI，不让其他客户端并发复用；锁仅约束合作入口，不为绕过 busy 换目录/账号或复制 token。

## 6. logout、迁移与撤权

```sh
python3 /actual/skill/scripts/pmcp.py logout oauth-service
```

logout 是经确认的本地认证清理，范围随版本变化，不等于撤销远端 grant，不保证运行任务取消；匿名/静态 key 的 logout 不替你撤销 API Key。服务端撤权在账号设置中按实际流程另获确认。

旧客户端/keyring 凭据、旧自选状态目录不自动导入，跨机器/跨版本不默认复制 token，见[私有存储与迁移](file-storage.md)。当前无后台会话/keepalive，不提供 close @session；关闭连接不是删除凭据或撤权。
