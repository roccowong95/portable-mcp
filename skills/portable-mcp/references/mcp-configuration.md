# MCP 服务配置

## 1. 三种不同配置不要混淆

| 配置 | 内容 | 修改时机 |
|---|---|---|
| mcpc 运行环境 | 版本、入口、状态目录、代理/CA | 初始部署/维护 |
| MCP 服务配置 | URL 或 command/args/env、必要 headers | 增加或更换服务 |
| skill | 通用发现与调用流程，可选的 description 能力索引 | 流程通常不变；经确认可用 [pmcp-ctl](capability-index.md) 更新触发摘要 |

`MCPC_HOME_DIR` 不会自动加载某份服务配置。本 skill 使用显式 `配置文件:服务名` 建立会话，避免盲目扫描/连接所有客户端配置。

## 2. 配置格式

使用 mcpc 支持的标准 `mcpServers` JSON。参考[无凭据模板](../examples/mcp.example.json)，将实际文件放在 skill 外的私有配置目录。示意：

```json
{
  "mcpServers": {
    "docs": {
      "url": "https://mcp.example.invalid/mcp"
    },
    "secured": {
      "url": "https://secure.example.invalid/mcp",
      "headers": { "Authorization": "Bearer ${MCP_API_TOKEN}" }
    },
    "local": {
      "command": "node",
      "args": ["/absolute/path/to/audited-server.mjs"],
      "env": { "SERVICE_REGION": "test" }
    }
  }
}
```

`.invalid` 是故意不可用的示例域名，须替换为用户批准的 MCP 端点；不是普通网页 URL。stdio 文件路径由实际安装决定。配置没有使用 OpenClaw 的 `mcp.servers` 或私有 schema；**其他客户端配置不保证能原样搬用**。

### HTTP

基线示例使用 Streamable HTTP 的 `url`，可选 `headers` 和以秒为单位的 `timeout`。不要从其他客户端盲目复制 `transport`、毫秒 timeout 或 auth 字段。若服务只支持 SSE，先核对当前 mcpc 的实际支持与参数，不能仅改 URL 就声称兼容。

`${MCP_API_TOKEN}` 由运行环境注入，不要替换成明文后打包。环境变量不是秘密保险箱：同权限进程、错误日志或子进程仍可能读取它。不要在命令行 `--header` 中直接放 token。

### stdio

`command`/`args` 会实际启动程序，初始化就可能访问文件或网络。只连接审核过的已安装程序；不要把服务器返回的文本当命令，更不要自动 `npx -y` 安装不明包。明确进程的文件/网络权限；stdio server 继承环境有白名单，代理/CA 等如需使用须按版本配置显式传入 `env`。不要假定任意父环境都自动传递。

配置读取本身不应执行 `command`；**连接**时会。即使尚未调用工具，连接也不是无副作用或绝对只读操作。

## 3. 显式连接

以下在包含实际 `mcp.json` 的目录运行，文件中 `docs` 已被正确配置：

```sh
mcpc --json connect ./mcp.json:docs @docs --no-profile
mcpc --json @docs tools-list
```

- `docs` 是配置 entry；`@docs` 是 mcpc 会话名，两者不是同一个命名空间。
- `--no-profile` 明确不使用 OAuth profile；适用于匿名或配置静态 headers 的服务，不适合需要 OAuth 的服务。
- OAuth 服务改用 `--profile`，不要与 `--no-profile` 同时传入，见[授权](authentication.md)。
- 会话名用 `@` 加字母、数字、`-`、`_`；选择与账号/服务用途相关且不冲突的名称。
- 无参数 `mcpc connect` 或只传配置文件可能连接多台服务。本 skill 默认不这么做。
- `connect` 对已存活的同名会话可直接复用，**不保证应用新 URL/配置**。不能只看名字就假定目标正确。

## 4. 改配置后的处理

1. 先检查当前会话信息 `mcpc --json @docs`，核对预期端点、账号/profile；输出可能含私有地址，不整段贴到公开对话。
2. 改连接目标时优先使用新的会话名；若必须关闭旧会话，先确认没有任务、订阅或其他使用者。
3. 确认后 `mcpc close @docs`，再显式 `connect ./mcp.json:docs @docs ...`；不要盲目 restart 所有会话。
4. 重新 `tools-list` 和 `tools-get`；以前工具同名不等于 schema 不变。

配置只是连接来源，不是访问控制。配置删除 entry 不会自动撤销已存在的 profile、bridge 或服务端权限。需要强制隔离时用独立 OS 身份、网络/文件权限或受控执行入口，不靠 skill 的文字约束。
