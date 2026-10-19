# MCP 服务配置

## 1. 唯一私有配置与首选流程

配置固定在 **OS 账号真实 home 下的 `.pmcp/config/mcp.json`**。POSIX 用 `pwd.getpwuid`，Windows 用系统 profile 定位，不采用环境 HOME/USERPROFILE，不提供路径或环境覆盖。先显式执行 `python3 <skill-root>/scripts/pmcp.py init`；`<skill-root>` 替换为实际 skill 安装目录。新代码不自动导入、迁移或复制旧状态/凭据，旧 `.portable-mcp` 保持原样；新部署须显式 init，并按用户批准的定义重新配置。

**Agent 新增服务必须使用 `config-add`，不手工编辑 JSON，也不整份复制其他客户端配置。** `init` 无需运行时；`config-add`（包括 dry-run）需要已安装运行时和现有 PATH Node。第三方运行时安装另需许可，见[安装约定](installation.md)。`pmcp.py meta-*` 只维护 skill description，无需 init、运行时或 Node，不访问账号状态或 MCP。

```sh
python3 /actual/skill/scripts/pmcp.py init
python3 /actual/skill/scripts/pmcp.py config-add docs --url https://mcp.example.invalid/mcp --dry-run
# 确认目标和配置后才实际新增
python3 /actual/skill/scripts/pmcp.py config-add docs --url https://mcp.example.invalid/mcp
python3 /actual/skill/scripts/pmcp.py servers
python3 /actual/skill/scripts/pmcp.py doctor
```

`.invalid` 是故意不可用的占位端点；换成用户批准的 MCP endpoint，而非普通网页。新增成功不证明服务可达、程序可信或业务已授权。

## 2. config-add 命令合同

```text
python3 <skill-root>/scripts/pmcp.py config-add SERVER
  (--url URL | --command COMMAND)
  [--arg VALUE ...] [--cwd absoluteExistingDir]
  [--oauth] [--header 'KEY=Bearer ${TOKEN}' ...]
  [--env 'KEY=${VAR}' ...] [--dry-run]
```

- `--url` 与 `--command` 必须且只能选一个；服务名精确使用配置 key。同名服务一律拒绝；当前没有 replace/remove 命令，不用变名或直接编辑绕过审核。
- 支持用户批准的完整 HTTP(S) URL，包括 `?token=...` 和其他 query，原样交给 backend，不剥离或改写 query；仍拒绝 userinfo、fragment、空白、反斜杠及无效协议/host/port。通常用 HTTPS，不为连接成功关闭 TLS 或擅自改用明文 HTTP。协议兼容性仍由所选依赖版本和服务决定。
- 含凭据的 URL 只保存到私有配置，不写入 skill、能力索引、示例、回复或日志；示例只用占位值。它不同于 OAuth callback/code，后者的安全规则不变。完整 URL 会进入原生配置 CLI 的 argv，即使在可信环境也不能保证其不可见；须由用户批准并在受控环境处理，不宣称秘密不会进入 argv。
- stdio 用 `--command`，参数逐个重复 `--arg`；以 `--` 开头的参数用 `--arg=--someflag`，不是原生 CLI 透传。command 必须非空；command/args 只放普通公开字符串，拒绝控制字符，且**禁止将秘密放进其中**；本入口不是可靠秘密检测器。优先使用经审核的绝对可执行/脚本路径，不能自动下载或安装服务器。
- `--cwd` 仅限 stdio，必须是实际已存在的绝对目录。配置命令不启动该程序；后续 tools/schema/call 连接时会真正启动。
- `--env` 可重复，值只能是环境引用，例如单引号保护的 `'SERVICE_REGION=${SERVICE_REGION}'`，不接受字面值（即使是公开 region）。`--header` 可重复，值只接受 `${VAR}` 或 `Bearer ${VAR}`，例如 `'Authorization=Bearer ${MCP_API_TOKEN}'`；不接受其他字面前缀。不放字面 token/key，不让 shell 提前展开引用。
- `--oauth` 标记 OAuth 配置，**不授权、不联网、不启动浏览器**。实际授权另获许可后用 `auth`，仍受现代版本门槛约束。不要混用 OAuth 和手写 Authorization，除非实际服务合同已审核。
- `--dry-run` 校验并预览，不发布到正式配置；仍要求显式 init、已安装运行时及 Node，不代表联网验证。
- 不接受 `--persist`、`--scope`、`--copy-from`、任意 native 参数或环境/路径覆盖。需要命令尚不支持的高级字段时**暂停并协调**，不能盲目手改 JSON。

示例仅展示格式，不是安装或连接授权：

```sh
# 仅占位 query，不含真实 secret；完整 URL 用引号保护，避免 shell 解释 & 等字符
python3 /actual/skill/scripts/pmcp.py config-add query-service --url 'https://example.invalid/mcp?token=EXAMPLE_ONLY' --dry-run
python3 /actual/skill/scripts/pmcp.py config-add secured --url https://secure.example.invalid/mcp --header 'Authorization=Bearer ${MCP_API_TOKEN}'
python3 /actual/skill/scripts/pmcp.py config-add oauth-service --url https://oauth.example.invalid/mcp --oauth
python3 /actual/skill/scripts/pmcp.py config-add local --command /absolute/bin/node --arg /absolute/path/to/audited-server.mjs --arg=--someflag --cwd /absolute/path/to/server-workdir --env 'SERVICE_REGION=${SERVICE_REGION}'
```

以上引用应原样进入配置；在实际运行环境以受控方式提供对应变量。环境变量也可能被同权限进程、日志或子进程读取，不是秘密保险箱。Windows 使用实际本机绝对路径及适用 shell 引号规则，不照抄 POSIX 路径。

## 3. 受控写入，不直写正式配置

包装器在固定 profile OS 锁内，对私有临时 JSON 调用已安装 `mcporter` 的原生 `config add`。原生配置阶段只接收受控目标（URL/command）和 auth 标记；args/env/headers 不传给原生 CLI，避免用户数据被原生全局开关解析。Python 随后合并已校验的 args/env/headers、显式 `lifecycle: ephemeral` 和所需 cwd。它验证 `imports: []`、现有条目未变及整个候选配置，最后原子发布到唯一配置。不能让原生 CLI 直接写正式配置：0.9/0.15 都有 config add，但旧版写文件不安全，原生命令本身不是本入口的写入安全保证。

整个 `config-add` 过程只做本地配置工作，**不发网络/MCP/OAuth 请求，不启动配置中的 stdio 程序**；运行原生配置 CLI 需要 Node，不等于连接 MCP。失败不应改动已发布配置。profile 锁只约束合作入口，不允许其他客户端或手工编辑并发改写。

## 4. JSON 格式参考与运行边界

保留[无凭据示例](../examples/mcp.example.json)作为**格式参考，不是 Agent 手工配置入口**。根 key 仅接受 `mcpServers` / `imports`，后者必须明确为 `[]`，避免默认导入其他客户端。每个服务显式 `"lifecycle": "ephemeral"`（验证器也接受仅含 `mode: "ephemeral"` 的对象）。所有业务命令包括 auth 都先校验配置，不静默修复或推断生命周期。

- 内部依赖真实 npm 包 `mcporter`；运行时仍为 `<skill-root>/scripts/.runtime/mcporter/`，本次只调整私有状态/配置位置，不宣称已完成所有内部文件名整理。
- 内部 HOME/USERPROFILE、四个 XDG 目录和 daemon 路径隔离在 `.pmcp` 内。stdio 的 `~` 和默认凭据不再指向真实用户 home；使用审核后的绝对路径与必要 env。
- 配置 env 不得覆盖 HOME、USERPROFILE，或 XDG_、MCPORTER_、PMCP_、NPM_、NODE_、COREPACK_、MCPC_、PORTABLE_MCP_ 前缀的隔离/控制变量；入口也清除继承的部署污染。业务变量如 MCP_API_TOKEN 不因固定部署而禁止。
- 不配置 `tokenCacheDir` / `token_cache_dir`；拒绝 refresh / refreshable_bearer、录制/回放或自定义自动刷新扩展。
- 已有配置中的 `allowedTools` / `blockedTools` 是精确名字过滤，不能并用；空 allowedTools 禁止全部。它不是服务端权限控制。`config-add` 尚无这些高级字段选项，需要时暂停协调，而非照着示例手改。
- 0.15 的新字段不自动适用于 0.9；只用核实的所选版本合同，见[来源](sources.md)。配置须严格 UTF-8 JSON，不含注释或重复 key，保持私有权限，不将含私有地址、headers/env 的完整文件贴到公开对话。

## 5. 服务名不是会话名

`servers` / `doctor` 离线，不启动 stdio，不发 MCP/OAuth 请求；`tools` / `schema` / `call` 仅连接指定服务。本版服务名精确等于配置 key，不接受 URL、近似名或 ad-hoc 定义，没有 connect/close/@session，也不连接全部服务。

当前命令只支持新增，不支持修改/删除已有服务。需要换 URL、headers、账号或高级字段时先暂停并协调批准的后续配置方案；不复用同名凭据、不通过手工覆盖/改名绕过限制。将来的配置变更后仍须重新发现工具与完整 schema；本地删除配置也不等于撤销服务端授权。
