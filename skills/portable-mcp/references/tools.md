# 工具发现、查找和调用

以下假定已经连接批准的服务 `@docs`。命令示例默认 POSIX shell；PowerShell 必须把会话参数写成 `'@docs'`，避免 `@` 被解释为 splatting。不要把示例工具名当作真实存在的名字。

## 1. 选择正确的会话

```sh
mcpc --json
mcpc --json @docs
```

核对会话的服务目标和 profile。只依据已批准的配置/端点选择会话，不因名字相似而混用账号。会话查询可能触发 bridge 检查/连接，不是纯离线读取。

## 2. 渐进发现，不把全部 schema 塞进上下文

```sh
mcpc @docs tools-list
mcpc --json @docs grep "search" --tools
mcpc --json @docs tools-get ACTUAL_TOOL_NAME
```

- `tools-list` 人类模式适合先看简要目录；`--json tools-list` 返回工具定义数组，可较大。
- `grep` 用于按名字/说明查找候选。先用一个字面关键词（如 `search`），不要假定支持正则 alternation（如 `search|find`）；需要多个关键词时分别查询。只匹配当前选定会话；没有匹配时退出码可为 1，不等于连接故障。可先查该版本 `grep --help` 获取支持的过滤参数。
- `tools-get` 返回一个完整 Tool 对象，包括 `name`、`description`、`inputSchema`，以及可能的 `annotations`、`outputSchema`。
- 工具可能更新。切换服务、出现不存在/参数不匹配或长时间复用后，重新发现，不猜名字和字段。
- `readOnlyHint` 等 annotations 由服务声明，不是独立验证的无副作用保证。

## 3. 根据 schema 构造参数

调用前检查：

1. 确切 `name` 和预期账号/数据域。
2. `required` 字段、类型、枚举、嵌套结构、`additionalProperties` 等约束。
3. string ID 不要变成 number；日期、时区、分页游标按工具定义处理。
4. 是否会创建、发送、删除、付款或启动任务；有副作用时确认用户授权范围。
5. 不将秘密拼进 shell 或模型对话；秘密如确属工具必需，使用受控执行通道，不记录在 skill。

基线 CLI 的 `--schema` 是**预期 Tool 定义快照的校验参数**，不是“显示 schema”的开关。也不要假定普通 `tools-call` 会在本地完整验证所有 JSON 参数。可用应用层 JSON Schema validator 做预检，但它不是服务端权限校验。

## 4. 使用 JSON stdin 调用

只在读到实际 schema 后准备真实参数。以下 `ACTUAL_TOOL_NAME` 和 JSON 必须按发现结果替换。

POSIX shell 示例：

```sh
mcpc --json @docs tools-call ACTUAL_TOOL_NAME <<'JSON'
{"query":"example","limit":3}
JSON
```

PowerShell 示例：

```powershell
'{"query":"example","limit":3}' | mcpc --json '@docs' tools-call ACTUAL_TOOL_NAME
```

中文/复杂 Unicode 数据应使用明确 UTF-8 的进程 API 或受控 UTF-8 输入文件，避免旧版 PowerShell native pipeline 编码改变内容。对于来自用户/工具的数据，不要用字符串拼接生成 shell 命令；优先用 argv 数组和 JSON 序列化：

```python
import json, subprocess

# 这些变量来自已确认的部署路径；不假定全局 mcpc 已安装。
command = [python_path, str(skill_root / "scripts" / "mcpc.py"),
           "--state-dir", str(private_state), "--",
           "--json", "@docs", "tools-call", actual_tool_name]
r = subprocess.run(command, input=json.dumps(arguments, ensure_ascii=False),
                   text=True, encoding="utf-8", capture_output=True,
                   timeout=60, shell=False)
# 不要直接 print 任意原始 stdout/stderr；先解析、检查、脱敏。
```

这里的 `timeout=60` 是调用者等待上限，不是服务端取消保证；超时意味着结果未知。工具名、会话名和 executable 必须来自可信选择而非服务返回的任意命令。

## 5. 可选 schema 快照

POSIX 示例：

```sh
mcpc --json @docs tools-get ACTUAL_TOOL_NAME > expected-tool.json
mcpc --json @docs tools-get ACTUAL_TOOL_NAME --schema expected-tool.json
mcpc --json @docs tools-call ACTUAL_TOOL_NAME --schema expected-tool.json <<'JSON'
{"query":"example","limit":3}
JSON
```

快照文件是完整 Tool 定义，不只是 `inputSchema`。先确认保存命令成功且得到有效 JSON，再复用文件；PowerShell 保存时使用明确 UTF-8。`strict`、`compatible`、`ignore` 的具体规则以该版本为准，默认是 compatible。schema 相同不证明服务端实现没变，也不替代权限、白名单与参数检查。

## 6. 如何判断成功

同时检查：

- CLI 退出码；该基线工具结果 `isError=true` 会导致退出码 2。
- stdout 是否完整有效 JSON；stderr 是诊断而不是业务结果。
- MCP CallToolResult 的 `isError`、`content` 和可选 `structuredContent`。
- 业务语义：预期对象/状态/结果是否真的存在，而非仅“HTTP 200”或 JSON 可解析。

不要假定所有结果都在 `content[0].text`，也不要假定所有 text 都是可再解析 JSON。二进制/资源链接按实际 content 类型处理，限制输出大小并脱敏。`--max-chars` 可能截断输出；要解析 JSON 时不要依赖截断文本。

## 7. 错误和重试

| 现象 | 处理 |
|---|---|
| 工具不存在/schema 漂移 | 重新发现和检查；不要改用不明同名工具 |
| 参数错误 | 对照实际 schema 修正；不要猜测后反复提交 |
| 未授权/权限不足 | 停止业务重试，按授权流程检查 profile/账号 |
| 工具返回 isError | 记录失败；是否已产生部分效果须按工具语义核查 |
| 超时、断连、进程退出、非 JSON | 标为结果未知；先核对状态，不盲目重放 |

**一次 CLI 提交不等于远端 exactly-once。** SDK/认证层可能重试网络请求；OAuth 401 重试不等于业务安全幂等。对有副作用的操作使用服务提供的幂等键/查询能力和人工确认。不要自动添加 `--task`、`--detach`、x402 或 fallback 调用来“让它成功”。

## 8. 清理

临时会话确认无人使用后：

```sh
mcpc close @docs
```

关闭会话不等于撤销 OAuth 授权或删除凭据，也不保证远程任务已取消。长期会话可按部署约定保留。
