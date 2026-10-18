# MCP 服务配置

## 1. 唯一的私有配置

先用固定入口 `init`，编辑其返回的 OS 账号真实 home 下 `.portable-mcp/config/mcporter.json`，而不是修改 skill 源码或扫描宿主配置。POSIX 以 `pwd.getpwuid`、Windows 以系统 profile 定位，不采用环境 HOME/USERPROFILE，不提供路径或环境覆盖，不自动迁移旧自选目录。根 key 只接受 `mcpServers` 与明确的 `"imports": []`；省略 imports 会让上游尝试默认导入其他客户端，不符合本版隔离合同。每个服务必须显式指定 `"lifecycle": "ephemeral"`（也接受仅含 `mode: "ephemeral"` 的对象），不依赖上游按服务名推断默认生命周期。所有命令（包括 auth）先校验配置，不自动改写配置。

| 对象 | 内容 |
|---|---|
| 内部运行时 | 自动选择后锁定的 mcporter、安装记录；现有 PATH Node/npm |
| 私有状态配置 | 服务名 → HTTP/stdio 定义、必要环境变量/headers |
| skill / 能力索引 | 通用流程和经用户确认的服务级触发摘要，不存凭据 |

以下为无凭据模板，见[完整示例](../examples/mcp.example.json)：

```json
{
  "mcpServers": {
    "docs": {
      "lifecycle": "ephemeral",
      "baseUrl": "https://mcp.example.invalid/mcp"
    },
    "secured": {
      "lifecycle": "ephemeral",
      "baseUrl": "https://secure.example.invalid/mcp",
      "headers": { "Authorization": "Bearer ${MCP_API_TOKEN}" }
    },
    "oauth-service": {
      "lifecycle": "ephemeral",
      "baseUrl": "https://oauth.example.invalid/mcp",
      "auth": "oauth"
    },
    "local": {
      "lifecycle": "ephemeral",
      "command": "/absolute/bin/node",
      "args": ["/absolute/path/to/audited-server.mjs"],
      "cwd": "/absolute/path/to/server-workdir",
      "env": { "SERVICE_REGION": "test" }
    }
  },
  "imports": []
}
```

`.invalid` 是故意不可用的占位端点，替换为用户批准的 MCP endpoint，不是普通网页 URL。可执行文件、脚本、cwd 都换成实际绝对路径；Windows 用本机路径与 JSON 转义，不照抄 POSIX 路径。

## 2. 字段与边界

- HTTP 优先 `baseUrl`，上游也接受 `url` / `serverUrl`。通常用 HTTPS；不为连接成功关闭 TLS 或擅自使用明文 HTTP。HTTP/SSE 的实际协议兼容性由所选版本/服务决定，不靠名字保证。
- `headers` 中的 `${MCP_API_TOKEN}` 在运行环境提供，不把 token 写进示例、argv、skill 或对话。环境变量也可能被同权限进程、日志或子进程读取，不是秘密保险箱。
- OAuth 明确 `auth: "oauth"`，普通发现/调用不启动授权；显式 auth 固定不自动开浏览器且仅支持 >=0.15，旧版失败关闭、无风险接受开关。旧版已有合法 token 的普通操作仍可，见[OAuth](authentication.md)。不混用 OAuth 与手写 Authorization，除非所选版本/服务合同已单独审核。
- stdio `command` / `args` 会启动真实程序，连接阶段就可能访问文件/网络。command 使用绝对可执行路径，cwd 如提供必须是已存在的绝对目录。只用审核并已安装的程序，不自动 `npx -y`、`uvx` 下载，不执行服务器返回的命令。需要安装服务器另获许可。
- 状态根由真实 OS 账号确定，内部 HOME/USERPROFILE 与四个 XDG 目录固定隔离在 `.portable-mcp`，不能由用户选择；stdio 子进程也受影响。`~`、默认配置/凭据不再指向真实用户 HOME；用绝对路径与显式所需 env。配置 env 不得覆盖 HOME、USERPROFILE，或 XDG_、MCPORTER_、PMCP_、NPM_、NODE_、COREPACK_、MCPC_、PORTABLE_MCP_ 前缀的隔离/部署控制变量；入口也清除继承的部署污染。固定部署不禁止 MCP 业务 token 环境变量（例如 MCP_API_TOKEN）。
- 不配置 `tokenCacheDir` / `token_cache_dir`；入口拒绝它们，使用私有共享 vault。首版拒绝 `refresh` / `refreshable_bearer`、录制/回放或自定义自动刷新扩展。
- 每个服务必须显式 `"lifecycle": "ephemeral"`；缺失、keep-alive 或其他模式都拒绝，不推断默认、不默默改写或降级。根级也不接受 lifecycle/daemon 等额外 key。
- 可选 `allowedTools` / `blockedTools` 是精确名字过滤，不能同时配置；空 allowedTools 表示全部禁止。入口发现和调用尊重过滤，但这不是服务端访问控制，不能防止绕过入口的其他客户端。
- 0.15 文档中的新字段（例如新认证/协议/daemon 选项）不自动适用于 0.9。参考[版本来源](sources.md)，只使用已核实的所选版本字段，不复制 main 文档当兼容保证。

## 3. 服务名不是会话名

```sh
pmcp servers
pmcp doctor
pmcp tools docs --query search
pmcp schema docs ACTUAL_TOOL_NAME
```

`pmcp` 为[固定入口](installation.md)简写。`servers` / `doctor` 离线，不启动 stdio、不发 MCP/OAuth 请求；`tools` / `schema` / `call` 仅连接指定服务。本版服务名必须精确等于本配置的 key，不能传 URL、拼写近似名或 ad-hoc 描述。没有 `connect`、`close`、`@session`，也不连接全部服务。配置名称不是权限、账号或端点验证的替代品。

修改 URL、headers、账号或 schema 后，下一次命令会读取新配置并创建新连接；重新发现工具及完整 schema，不假定旧定义仍有效。同一名字换 URL 可能改变 OAuth 身份绑定，先停下正在执行的工作并核对账号/授权，不凭名字复用旧 token。删除配置不等于撤销服务端 grant。

配置是严格 UTF-8 JSON（不加注释/重复 key），放在 skill 外并保持私有权限。修改时避开正在执行的命令，手工编辑不会自动获得入口锁。不要将带私有 URL、headers 或 env 的完整配置贴到公开对话。
