# OAuth 与凭据

## 1. 先区分三种服务

- **匿名服务**：连接时 `--no-profile`，无需 OAuth。
- **静态 API Key/Bearer**：管理员以受控环境变量和配置 header 提供；`--no-profile` 不会删除这些显式 header。
- **OAuth 服务**：由 mcpc 登录并保存 profile，后续连接显式选择 profile。不要再由 skill/shim 抽取和维护一套 AT/RT。

不要因为连接失败就自动发起授权；先确认服务类型、目标账号及权限范围。

## 2. OAuth 常规流程

**先过安全门槛：此固定 0.7.0 的 callback state 校验缺口适用于真实 OAuth，不只手工回调。默认不自动开始真实登录。先采用已审核修复版/可信完整回调校验方案，或由管理员明确评估并接受风险；功能能跑通不等于安全验收通过。** 文件存储补丁不解决此问题。

以下仅展示接口，不是立即执行指令。端点是占位符；通过上述门槛并获得实际账号授权许可后才操作，流程会访问网络、打开浏览器和写入凭据：

```sh
mcpc login https://mcp.example.invalid/mcp --profile work
mcpc --json connect https://mcp.example.invalid/mcp @work --profile work
mcpc --json @work tools-list
```

0.7.0 没有已验证的 `login --code` 两阶段入口。不要编造 `--code`、`--no-browser` 或强制文件存储环境变量。先用 `mcpc login --help` 核对当前版本。

`--profile` 与显式 `Authorization` header 不应混用；基线 CLI 会拒绝这种组合。账号发生变化时使用独立 profile，不能只凭同一个服务 host 就假定身份正确。

## 3. 无桌面/远程服务器

浏览器可在用户电脑上，mcpc 在远端；浏览器中的 localhost 指向用户电脑，不是远端服务器。

可以由管理员按实际支持选择：

1. **受控回调转发**：把已确认的 loopback 回调端口经 SSH 转发到远端；只绑定本机，不暴露到公网，结束后关闭。
2. **手工 URL 回传**：0.7.0 在打开浏览器失败时有 stdin 粘贴 callback URL 的路径。原登录进程必须保持存活，PKCE/verifier 不因重新启动自动恢复。通过私有终端/受保护 stdin 传递，**不要让用户把含 code 的完整 URL 发到模型聊天**。

遇到 0.7.0 需要特别谨慎：已有源码/离线测试发现 flow 没有把收到的 callback state 与预期 state 对照，而实际 SDK 明确由调用方校验。手工 URL 场景应在可信回调处理器中校验 scheme/host/port/path、唯一且非空 code、精确 state、错误字段及 issuer 合同等，或使用已经修复并审核的版本；本 skill **不提供通用安全回调监听器，也不宣称修复了上游问题**。验证通过的授权 URL 可交给用户，AT/RT、verifier、code 不交给模型。

不要从聊天记录重放旧 code，不要在 shell argv 中传 code/token。登录日志、浏览器历史和 debug 输出可能含敏感信息，必须保护。

## 4. 凭据保存位置

mcpc 优先使用 OS keychain；不可用时可回退到状态目录内的 `credentials.json`。这不是“所有状态都只在 `MCPC_HOME_DIR` 内”的保证：

- profile 元数据与会话文件在状态目录；
- OS keychain 使用固定 service `mcpc`；0.7.0 凭据键由 server host（含非默认端口）和 profile 等组成，不含状态目录，也不完整区分 URL path/scheme；
- 因此新建状态目录不等于隔离现有 keyring 凭据。需要独立 OS 身份、明确 profile 命名或已审核的独立后端。

无桌面 Linux 的 keyring 依赖可能退到内存后端，当前进程写读成功不代表新 SSH/重启后可用。若明确选择文件存储，读[可选文件后端](file-storage.md)。它是当前基线的**本地补丁**，不是上游现成开关。

## 5. 持久性与刷新验收

应分别验证，不能互相替代：

1. 登录成功，profile 对应正确服务/账号。
2. 同一进程/SSH 下连接和发现成功。
3. 退出并新建 SSH/exec，仍用相同入口、身份和状态目录，可以连接和发现。
4. 真实凭据到期后，mcpc 能刷新、保存并继续使用。

访问令牌过期不一定需要用户重新授权；refresh token 被撤销/失效则可能需要。refresh token 更新不等于服务端一定实施“轮换”。

0.7.0 已审计路径没有跨进程覆盖“读取→刷新→持久化”整个事务的锁。并发刷新、轮换及写入失败有风险；文件存储不会修复它们。多 worker 运行时使用受控单实例/串行执行或经审计的新实现，不要宣称独立文件锁就解决了刷新竞争。

## 6. 迁移与退出

迁移 skill 时不迁移 token。需要迁移运行环境时，profile 元数据、凭据后端、客户端注册及身份绑定须整体审核，不能只复制一个 access token。按服务支持重新授权通常更清晰。

`close` 仅结束 mcpc 会话；logout/删除本地凭据也不一定撤销服务端 grant。需要撤权时按服务和 mcpc 当前版本流程操作，先获得用户确认。
