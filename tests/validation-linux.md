# Linux 技术验证记录

验证时间：2026-10-19（Asia/Shanghai）。源码基线：`cc9fd1d`，另加本次新增的开发诊断与 smoke 脚本；发布内容未进一步修改。

## 环境与操作边界

按仓库约定经双跳 SSH，在 `/root/workspace/portable-mcp-verify-l2q3rq3g` 同步当前本机源码与测试。该目录仅用于技术验证，不替换部署内容；同步目录保留供复查，测试创建的临时 fixture 目录已自行清理。

本次未安装、更新或替换 Node/npm/mcporter；未修改全局 PATH、已部署插件、真实 MCP 配置或凭据；未进行 OAuth、真实业务调用或停止业务进程。服务 PATH 只用于单条诊断命令，不写入 shell 配置或服务配置。

## Node 双版本诊断

保留的诊断脚本只采集当前账号/SSH PATH、可执行路径、版本、部分安装记录、服务进程名称/可执行文件/工作目录，不打开进程环境文件或读取进程参数、真实配置及凭据文件。

隐私边界更正：本次初始诊断为提取服务 PATH，曾把 `/proc/<pid>/environ` 整体读入内存后筛出 PATH；未输出或保存其他字段，但这不符合“完全不读取其他环境值”的严格边界。静态复核发现后，已从保留的脚本移除该读取，不再重复此方式。下表服务 PATH 属于该次历史观察，重新运行诊断脚本不会输出它。

| 证据 | 结果 |
| --- | --- |
| 当前 SSH 优先解析的 Node | `/usr/bin/node`，`v24.21.0` |
| SSH PATH 中另一候选 | `/usr/local/bin/node` → `/usr/local/node/bin/node`，`v22.23.3` |
| OpenClaw 与插件适配服务进程的可执行文件 | `/usr/local/node/bin/node` |
| 上述服务进程 PATH | `/command:/usr/local/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin` |
| 已安装 mcporter 记录 | `0.9.0`；安装时 Node `v22.23.3`；可执行路径 `/usr/local/node/bin/node` |
| 安装记录 npm CLI | `/usr/local/node/lib/node_modules/npm/bin/npm-cli.js` |

结论：SSH 与服务的 PATH 优先级不同，确有两套 Node。SSH 默认入口会把当前 `v24.21.0` 与安装记录 `v22.23.3` 比较，命中已有的 Node 版本漂移保护；并非本次操作升级了 Node，也不能因此直接重装线上运行时。进程环境证据不保证将来每个 Amoo `exec` 子进程的环境相同；后者仍须在实际会话中核对。

## 已部署原入口的 SSH 只读检查

使用既有原路径 `/root/.openclaw/workspace-task/skills/portable-mcp/scripts/`，在单条命令中指定上表服务 PATH。未复制、改名或链接线上入口以绕过授权网关。

| 命令 | 输出摘要 | 退出码 |
| --- | --- | --- |
| `python3 mcporter.py version` | `mcporter 0.9.0`，Node `/usr/local/node/bin/node` | 0 |
| `python3 mcporter.py servers` | `{"servers":[]}` | 0 |
| `python3 mcporter.py doctor` | `ok:true`，Node `v22.23.3`，ephemeral，缓存 OAuth 可用标识、交互授权 false、toolRetries false | 0 |
| `python3 install_mcporter.py --check` | `already-installed`，`network:false`，engineRange `>=20.11.0` | 0 |

`doctor` 的功能字段是版本能力声明，不是 OAuth 实测结果；空服务列表没有验证真实服务。安装检查只复用既有安装，不访问 registry 或安装依赖。

## 隔离回归与真实运行时 smoke

以下验证在同步目录中执行，使用现有 `/usr/local/node/bin/node`（`v22.23.3`）：

| 验证 | 结果 | 证据范围 |
| --- | --- | --- |
| `python3 -m unittest discover -s tests -p 'test_entry.py' -v` | **17 passed** | 固定 home、隔离环境、配置/权限/锁/损坏 vault、部署选项拒绝、离线复用、实际 npm semver；多数入口依赖使用 mock/temp fixture |
| `node --test tests/test_bridge.mjs` | **35 passed** | fake 0.9/0.15 公共 API、精确名、无重试、错误脱敏、原始结果、关闭资源、分页、cwd；不等于实测安装了 0.15 |
| `python3 tests/smoke_runtime.py --node ... --package ...` | **5 scenarios passed** | 既有真实 mcporter 0.9.0，加临时本地 stdio MCP fixture；不使用真实账号配置/vault |

Smoke 场景：

1. `tools` 发现本地 fixture 工具，退出 0。
2. `schema` 返回其 inputSchema，退出 0。
3. `call echo_fixture` 保留 MCP 结果及 `_meta`，退出 0。
4. fixture 返回 `isError:true`，保留原始结果并退出 2。
5. `call echo_fixtur` 拼错名称，拒绝且退出 1，不纠正名称、不额外执行。

fixture 日志只记录到 **2 次**预期工具执行；私有临时 HOME/XDG 中未创建 OAuth vault。每场景均在独立进程组运行，结束或异常/超时时强制清理该组剩余进程并回收 bridge；这保证了 fixture 清理范围，不作为“正常优雅关闭”的证据。本次未验证 HTTP/SSE、真实服务、OAuth、刷新、并发刷新或 Windows。

一次批量同步初尝试因 `python3: Argument list too long` 失败，出现的“0 tests”不算通过；改用 stdin here-document 传输后重新执行，上表统计来自成功执行的最终结果。

## Amoo 集成验收：仍未通过

本记录仅是直接 SSH 技术验证，不取代云端 Studio 处理/发布/安装及 adb 新会话验收。`cc9fd1d` 的 `src/` 新布局尚无用户重新发布安装确认，因此本次未声称验证其部署结果。

此前 Amoo 原始入口调用被宿主授权网关拦截。历史记录中的工具为 `exec`，命令参数：

```sh
python3 /root/.openclaw/workspace-task/skills/portable-mcp/scripts/mcporter.py version; echo "exit=$?"
```

原始响应（来自此前 Amoo 历史，并非本次 SSH 输出）：

> 使用「金山文档」需要先完成OAuth 授权。请提示用户点击对话中的授权卡片完成授权。禁止代用户调用 /v1/oauth/sessions、/v1/auth/sessions 或 client_action 中的接口；不要在对话中索要 Key。用户完成授权后再重试原请求。

该调用未产生脚本 stdout 或退出码；具体关联原因未确定，不能从提示推断匹配规则。此前 Amoo 自行使用临时链接得到的诊断不计入原入口验收证据；不应继续通过链接、复制入口、改名等绕过宿主网关。SSH 原入口成功只证明在所述命令环境下运行正常，**不证明 Amoo 网关已放行**。

剩余验收：用户从 `src/` 发布/安装并确认后，以 Amoo 新会话验证 skill 发现与原始入口；若仍被拦截，保留原错并由宿主排查。真实服务及 OAuth/刷新需另行许可与独立验证，尤其当前 Node 22 对应的 0.9.0 在本入口中禁止新 OAuth 授权。
