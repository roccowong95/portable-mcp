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

本轮技术验证时的剩余验收：用户从 `src/` 发布/安装并确认后，以 Amoo 新会话验证 skill 发现与原始入口；若仍被拦截，保留原错并由宿主排查。真实服务及 OAuth/刷新需另行许可与独立验证，尤其当前 Node 22 对应的 0.9.0 在本入口中禁止新 OAuth 授权。

## 发布确认后的 Amoo 复测（2026-10-19 02:25，Asia/Shanghai）

用户确认已发布并要求继续测试。通过 adb 连接设备 `ZYPZ261A01M68R000F2`，在 Amoo 界面创建新会话，发送只读验收请求：加载已安装 portable-mcp skill，以原始 Python 入口执行 version、servers、doctor；禁止安装、更新、init、OAuth、业务调用及任何绕行。

观察结果：

- Amoo 报告先通过 `read` 成功读取 `/root/.openclaw/workspace-task/skills/portable-mcp/SKILL.md` 正文第 1–65 行，包含“固定策略与有限业务入口”和稳定命令表。该证据来自实际会话回复及其历史自查，支持 skill 可发现/可读取；没有据此声称核验了部署包完整 hash。
- 随后唯一一次 `exec` 的命令参数如下，仍在执行前返回上节所保留的同一金山文档 OAuth 提示，并出现授权卡片。

```sh
cd /root/.openclaw/workspace-task/skills/portable-mcp && ls scripts/ && python3 scripts/mcporter.py version
```

- 未得到 shell/script stdout 或退出码。第一条受阻后未继续 servers、doctor。两者未验证，不计为脚本自身失败。
- 未点击授权，未安装/更新运行时，未做 OAuth、业务调用或替代入口。后续仅要求 Amoo 从现有会话历史解释工具名和读取证据，不再执行工具。
- Amoo 曾推断“网关误匹配”，但本记录不采纳该根因断言：实际触发规则及为何关联金山文档均 **unknown**。

结论：发布后的 skill 发现/读取有会话证据，**原始入口执行及端到端验收仍未通过**，需要宿主侧排查上述 `exec` 的授权关联。新的真实业务/OAuth 验证并未获得额外许可，也未执行。

附：此前 push 网络中断的验证资料提交 `8eb970854c64690f889cd2e9b1e2e3f161b26856`，本次重试得到 `Everything up-to-date`，并通过 `git ls-remote origin refs/heads/main` 确认该 hash 已在远端；这只说明源码同步状态，不等于部署状态。

## portable-mcp 中性入口整理后的回归（2026-10-19）

源码基线为 `94fa596` 加本次未提交改动。四个实现文件改为 `pmcp.py`、`install_runtime.py`、`mcp_bridge.mjs`、`runtime_versions.cjs`；真实 npm 包、安装标记和私有配置/vault 路径保持兼容，不自动迁移凭据。`version` 改用 `backend:{package,version}`；`doctor` 同样用 backend 替代旧 mcporterVersion。

本机开发后经同一双跳 SSH，将 9 个当前文件同步到独立目录 `/root/workspace/portable-mcp-verify-neutral-vyh_2f1x`。使用现有 Node，将 `/usr/local/node/bin` 仅前置于测试子进程 PATH；未改全局 PATH 或替换 Node。结果：

| 验证 | 结果 | 证据范围 |
| --- | --- | --- |
| `python3 -m unittest discover -s tests -p 'test_*.py' -v` | **21 passed，0 skipped** | 19 项入口/semver（含新增 init 幂等保留配置、Node 漂移拒绝），加能力索引和 Python→Node 进程合同；使用 mock/temp fixture |
| `node --test tests/test_bridge.mjs` | **35 passed** | 两个版本分支的 fake 公共 API，精确匹配、原始结果/退出码、分页、关闭与错误边界 |
| 本机相同两套命令 | Python **4 passed、17 skipped**；bridge **35 passed** | Windows 跳过 Linux 权限、锁及进程合同，不能算 Linux 测试通过 |

进程合同测试覆盖 init→配置→version/servers/doctor→tools→schema→stdin call；数字样字符串、中文/emoji、空串、嵌套对象/数组保型，保留 `_meta` 与 isError；拼错工具和非对象输入均不额外 dispatch。能力索引仅在复制的 skill 上 add/dry-run/sync/remove，最终内容恢复原样。

本次没有下载、安装或更新第三方运行时，没有使用真实账号配置/vault、没有 OAuth 或业务调用。已部署 skill 的 runtime 目录在本次检查时不存在，故**未重跑真实 mcporter smoke**；上文真实 0.9.0 smoke 仅为此前基线的历史结果，不算当前入口验收。没有为弥补此缺口而安装依赖或改动部署内容。

该轮验证不等于真实 mcporter 0.15、HTTP/SSE、OAuth 回调/持久化/刷新、并发刷新、Windows 生产环境或 Amoo 端到端通过。提交与 push 后仍须用户在 Studio 发布/安装并确认，再开始 Amoo 新会话验收。中性命名用于明确产品与后端边界，不作为绕过宿主授权网关的方案。

## 淘宝镜像与统一能力索引入口回归（2026-10-19 23:30，Asia/Shanghai）

基线 `1cd464b6afdbdc74bb86251aae021c8154d31008` 加本次修改：安装器固定 `https://registry.npmmirror.com/`；删除三个 mcpc 退役提示脚本；将原独立能力索引实现并入 `pmcp.py meta-*` 并删除独立入口。保留 Node bridge 与 npm semver helper，不改变 MCP 业务合同及私有配置路径。

先只读核对双跳 SSH 的 uid、PATH、两个现有 Node 版本及部署安装记录是否存在：SSH 默认 `/usr/bin/node v24.21.0`，另有 `/usr/local/node/bin/node v22.23.3`；部署安装记录不存在。没有读取配置、vault、进程环境或参数。随后将当前 `src/` 及三份回归测试同步至新建隔离目录 `/root/workspace/portable-mcp-verify-unified-4cq5i__2`，在各测试子进程单独选择既有 Node，不修改全局 PATH。

| 环境 | Python unittest | Node bridge tests |
| --- | --- | --- |
| Linux，既有 Node `v22.23.3` | **34 passed，0 skipped**，9.945 秒 | **35 passed，0 skipped** |
| Linux，既有 Node `v24.21.0` | **34 passed，0 skipped**，9.978 秒 | **35 passed，0 skipped** |
| 本机 Windows | **17 passed，17 skipped**（共 34 项），5.627 秒 | 本轮未重跑 |

新增证据：能力索引真实 CLI 使用只含 Python 入口及其标准库安装模块的 skill 副本、清空 Node PATH，覆盖 add/list/remove/sync、merge/replace/dry-run/幂等、索引锁、输入限制、重复 JSON/YAML、CRLF/mode 及非目标字节保留；独立 guard 断言 meta 分派不调用任何账号状态、运行时、Node 或执行函数。安装器使用 mock registry/npm 边界，检查淘宝请求、精确安装参数、净化环境和安装记录；**未进行真实 npm install**。业务进程合同和 bridge 仍使用 fake 后端 API，不代表真实 mcporter 联网验收。

此外，本机只读 GET 淘宝镜像 `/mcporter/latest` 成功，返回包名 `mcporter`、版本 `0.15.0`、Node engine `>=24`。这只证明该次元数据端点可达，不能代替完整依赖下载/安装或未来可用性。

本轮未安装/更新任何第三方运行时、未升级 Node、未覆盖部署内容、未读写真实账号配置或凭据、未执行 OAuth/真实业务/Amoo 新会话。现有安装默认离线复用；镜像策略变更不会自动重装。最终宿主验收仍遵守用户发布/安装确认后的顺序。

## 新配置路径与受控 config-add（2026-10-20，Asia/Shanghai）

本机修改：固定账号状态根改为真实 OS home 下 `.pmcp`，唯一 MCP 配置为 `config/mcp.json`；`init` 不读取、复制或迁移旧 `.portable-mcp`。添加 `pmcp.py config-add`，由既有原生 `config add` 在私有临时空配置中生成一个服务定义，Python 再补 args/cwd/env/headers、强制 ephemeral，验证 imports/权限/整个候选配置并在 profile 锁内原子提交。拒绝同名覆盖及 native 参数透传，失败保留原配置。

只读 preflight：SSH uid=0，默认 PATH 对应 `/usr/bin/node v24.21.0`、npm 11.19.0；实际已部署 skill 安装记录为 mcporter 0.9.0 / Node v22.23.3，可执行 `/usr/local/node/bin/node`。本次仅读取安装记录的 package/version/nodeVersion/cli，不读真实配置或凭据；未把 SSH 默认 Node 当作 Amoo 的 Node。

当前源码与回归同步到 `/root/workspace/portable-mcp-verify-config-f72x5y5b`；使用各测试子进程局部 PATH 选择既有 Node，不改全局环境。

| 环境 | Python unittest | bridge |
| --- | --- | --- |
| Linux，既有 Node v22.23.3 | **55 passed，0 skipped**，13.892 秒 | **35 passed，0 skipped** |
| Linux，既有 Node v24.21.0 | **55 passed，0 skipped**，13.903 秒 | **35 passed，0 skipped** |
| 本机 Windows | **37 passed，18 skipped**，6.874 秒 | **35 passed，0 skipped** |

新增 20 项配置回归及 1 项真实 Python→Node fake-native CLI 流程：HTTP/OAuth 标记/header 引用，stdio args/cwd/env 引用，单次原子发布、失败/非法输出/重复 JSON 保留、dry-run 字节与 inode 不变及临时清理、旧目录不迁移、并发修改与晚采样丢更新防护、名字/URL/隔离变量/秘密字面值/透传参数拒绝。Windows 的配置语义测试 mock ACL 检查，不构成 Windows ACL 安全验收。

另直接使用**已安装** mcporter 0.9.0（未下载/安装/更新）做两层真实包验证：

1. `/root/workspace/portable-mcp-native-add-_0_26xyn`：原生 HTTP/stdio `config add` 均 exit0，生成 JSON 的 `baseUrl`/`command` 与 imports 形状符合适配器预期。
2. `/root/workspace/portable-mcp-real-add-fixture-negcp_0t`：从同步源码导入 pmcp.py，仅在测试驱动中 patch home/runtime/安装锁到隔离 fixture 与既有只读依赖；执行 init、dry-run、HTTP 环境 header、新增 stdio 的 args/cwd/env，验证新路径、imports[]、ephemeral、参数与引用原样保留及无遗留暂存目录。未新增任何生产可用的路径覆盖或测试开关；这不是原始部署/Amoo 入口验收，也不证明安装锁集成。

真实包探针的 MCP endpoint 为 `.invalid` 占位符，stdio command 为 never-spawn fixture；只运行配置 CLI，不启动目标服务、不执行 MCP/OAuth/刷新或真实业务。未覆盖实际插件、改动实际配置/凭据或升级 Node。真实 mcporter 0.15 配置 CLI 未实跑（仅源码核实和 fake API 回归）；新代码尚未通过用户发布后的 Amoo 集成验收。运行时仍在 skill-local `.runtime/mcporter`，本次仅先调整私有配置/状态位置，不宣称已完成全部运行时文件名整理。
