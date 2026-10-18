# Amoo 架构对照与免反复发布的开发验证方案

调查时间：2026-10-19 02:45–02:55（Asia/Shanghai）。本机源码基线 `8431008`。本轮目标是调研和只读定位，不是修复线上授权或验收真实业务。

## 1. 目标与执行边界

沿用 portable-mcp 的 **B 路线**：手机读取固定 skill，经既有 `exec` 执行客户端，完成 MCP 任务。不是 A「手机原生新增 tool」，也不能把 C「SSH 服务端客户端调用」冒充 B。

本机读取 `stepx-amoo-arch` 的 architecture、evidence-and-sources、debug-and-development 三份参考；对照历史 skill 发现和手机 mock 报告。经双跳 SSH 只读核对当前进程、端口、实现源码、指定配置字段、部署元数据和既有日志。未启动新的手机任务或 MCP 调用，未抓包、启用调试、重放 RPC、请求 OAuth、安装插件、改配置或重启服务。

配置 JSON 仅为提取指定字段及哈希在内存解析；未输出完整配置、token、进程参数、进程环境、聊天/笔记原文。日志只输出必要方法、时间、行号和关联 ID 哈希，不保存原始正文。普通 SSH、GET 访问仍可能产生服务访问记录。

## 2. 架构对照：当前事实与历史证据分开

```text
手机 / 上游编排                 ← 当前未取得其源码和权威 tools schema
  → botagent 的既有 builtin exec/read
       → Python 固定入口 → mcporter → MCP
  → plugin-adapter 的工具 / hooks 分支

原生 OpenClaw Gateway           ← 并存，不证明每次手机 exec 必经此处
  → 自己的 Agent / plugin / MCP runtime
```

三份目录分别是：原生 OpenClaw catalog/effective、adapter registry、手机当前回合 tools schema。前两者不能替代第三者。

### 当前只读基线

| 组件 | 当前观察 |
| --- | --- |
| 目标 | 双跳后的主机 `99896e5c`，UID 0 |
| envd | PID 96，startTicks `82` |
| botenvd | PID 1056，startTicks `445337` |
| botagent | PID 4288，startTicks `5430039` |
| adapter Node | PID 4289，startTicks `5430039`，cwd `/root/.plugin-adapter-service/source` |
| 原生 OpenClaw | PID 4311，startTicks `5430066` |
| 其他既有 Node | PID 31755，startTicks `11181733`，cwd `/root/.openclaw/mcp-private`；未操作 |
| TCP loopback | 18700、18789、18790 可连接；仅端口正控，不算业务健康 |
| botagent runtime 目录 | `GET /v1/runtime/tools` 返回 version 1：exec、process、read、web_fetch、write |
| adapter 包 | `plugin-adapter-service 0.2.6` |

botagent 二进制 SHA-256 与历史报告一致：`1c0624f020ebc321c3407894639ee2fdcec2caf8ce9475ec0e36dd19d5aec87f`。adapter bundle 同样一致：`b9624b4c18406c8246be7412631fcb973bffe078572cd0f006b932c0366ced0f`。

历史报告通过“精确指定 shell 命令、botagent 父进程、手机回显”验证过 exec 的目标执行。它支持所述路线的可行性，但不证明当前被拦命令曾执行，也不提供本次修改/绕过授权。

## 3. 金山文档 OAuth 提示：定位到哪里，没定位到哪里

此前发布后新会话的直接证据已记录于 [Linux/Amoo 验证记录](validation-linux.md#L81)：skill 可读取，`exec` 首次调用收到金山文档 OAuth 提示，无 shell stdout 或退出码。

### 本轮静态源码与既有日志发现

1. adapter bundle、自有插件目录的 50 个有界实现文件，以及 botagent 二进制，未命中该拒绝文案、`/v1/oauth/sessions` 或 `/v1/auth/sessions`。不扫描配置/凭据作为文案库，不把依赖或上游服务包含在该阴性结论内。
2. `security-guard` 确有 `before_tool_call` 裁决路径：把 tool/params/subjects 与关联信息交给本地规则、memo 或远程 `requestAdjudication`；可返回 `{block:true, blockReason}`。**存在这段代码不代表它导致本次提示。**
3. 该版本 `formatBlockReason(response)` 固定返回 `[Security Guard] ${reason}${suffix}`。手机看到的原始文案没有此前缀。它只是不一致线索，不能排除上游另作格式化或另一个裁决器。
4. `tool-hooks-observer` 的已读 before hook 主要记录/上报 trace，末尾 `return void 0`。hook 活动不是工具执行证明，也不是授权成功证明。
5. adapter `config.yml` 指向 `/root/.openclaw/openclaw.json`；该 JSON 的 `plugins.entries` 没有 security-guard、tool-hooks-observer、ability-params-inject 的显式项。**缺项不等于禁用**：插件默认加载、启动配置和进程内状态仍需分别辨认。
6. security-guard 既有插件日志停在 2026-10-17 17:19 UTC 的初始化记录，没有本次目标事件。botagent 当天日志在复测附近有 builtin/hook/skill.paths 元数据，但不含 portable-mcp 或金山文档字符串，不能逐条关联目标 exec。方法匹配行数不是独立执行次数。

### 当前结论

本轮安全调研已形成阶段性结论：本地存在可阻断的安全 hook，但已读源码、文案差异与既有日志不足以将本次拒绝归因于它；不应通过停用安全组件或换入口规避。gate 文案生成层、命中规则及授权关联根因仍为 **unknown**。

- 已验证：拒绝早于获得原入口脚本输出；MCP 服务 OAuth 与这个宿主提示是两件事。
- 支持的假设：上游的工具/skill 身份、产品服务映射或授权包装层值得优先查；不是通过反复重装 mcporter 能解决的问题。
- **未验证**：究竟哪个进程/服务生成提示、哪一条规则命中、是否是错误关联、原始上游 tool-call ID 与授权 rule/provider 的对应。
- 因此不停止 security-guard/OpenClaw，不修改 `grpc_only`，不清缓存、不删授权状态，也不换入口躲过同一个拒绝。

## 4. 新发现：部署脚本一致，skill 正文仍有旧指令

当前四个核心脚本部署哈希与本机相同：

| 相对 skill 路径 | SHA-256 |
| --- | --- |
| `scripts/mcporter.py` | `f8913870691d6391e796b03ce4fa3b65667611d7499cbc36478ea91e8b8d92f1` |
| `scripts/mcporter_bridge.mjs` | `975e89c947a56371fe0ec5578f010986294e0292b9057df11469e60ba9a62d30` |
| `scripts/install_mcporter.py` | `2af9365c51e85de8ce308c17432a2cdba72d410a0642b96cd1e8d4c4ca965855` |
| `scripts/mcporter_versions.cjs` | `3d9bb9558ce3d3639b4ffa1936e31ce91bfcfcc3adc96e1776deb60adb6b8407` |

部署的 `SKILL.md` 为 65 行、7547 bytes，哈希 `3e73b2a2c67433b4e1f9be7921c0e583f1c061e65b864f921c52c7dd5f741c32`。本机当前正文为 64 行，哈希 `8503ad463a72d18c95b19cbcf99eeb6bb3e5458f16c5f450616ff6bd06de93a1`。

按行对照只有部署正文第 50 行多出旧指令：

> 遵循[仓库要求](../../AGENTS.md)：**commit + push → 用户手动安装 → adb 启动 Amoo → 新会话测试**；提交前不执行测试，源码审阅不等于应用验收。

它与当前本机开发约定不一致，且发布正文引用了包外开发文件。不能据此认定 Studio 如何加工了文件：可能是构建输入、模板或版本选择，**注入来源未查明**。也没有证据把这行与金山文档授权提示建立因果。

安全 origin 元数据仅确认安装版本 `0.6.0`、registry host `biz-gw.stepos.com`、安装时间；没有读取 registry 鉴权、发远程 registry 请求或修改安装记录。后续核对发布输入时，应同时比较文档哈希与脚本哈希，不能只看版本号或“发布完成”。

## 5. 推荐的快速开发闭环：技术迭代和最终发布拆开

### 现在就可采用：本机开发 + SSH 隔离技术验证

- 本机编写代码与 fixture，按内容哈希同步到 `/root/workspace/` 的独立验证目录。
- 明确选用现有服务 Node；不改变全局 PATH，不升级/替换系统 Node，不自动安装依赖。
- 基础层直接使用临时本地 MCP fixture 和既有 runtime；固定账号真实状态入口使用 mock/temp fixture 测函数，或只运行经许可的真实只读命令，不能加偷偷重定向生产状态的测试后门。
- 服务器回执独立记录无秘密的 request/nonce、工具名、结果摘要。真实已提交的副作用请求超时标为未知，不重放。
- 手机端 UI/宿主行为可用 adb 观察，但服务端测试和手机调用分别标注。此阶段完全不需要每轮 Studio 发布。

### 可行性有历史证据，但当前尚未实施：一次建立固定开发入口

历史 workspace 临时 skill + exec + mock 曾成功，不必每轮 Studio。它不是当前平台热部署契约，也不自动解除当前 gate。

建议在宿主确认适用的开发/测试权限边界后，建立一个**固定且公开标注 dev-only 的测试入口**，后续只更新验证目录的 payload，不修改正式 skill 或生产配置。需具备：

1. 固定路径/身份，显式允许的测试操作和 fixture；仍走正常宿主鉴权，不通过命令混淆、改名或链接规避。
2. 每轮测试签入/记录 payload 哈希与 nonce；手机只能获得入口和任务，不预喂预期结果。
3. 同回合手机 tool-call 标识、目标进程（必要时仅 PID/祖先名）、本地 MCP receipt 与手机结果摘要关联。没有关联就不声称闭环。
4. 限时、无真实业务、无 OAuth、无生产凭据，退出时清理自己的子进程/临时状态；不修改账号主 PATH。
5. 原始被拒入口仍单独记为未通过；dev fixture 成功不证明它已放行，也不冒充正式插件部署验收。

本轮没有创建这个入口、写 workspace skill、修改 adapter 或通过 adb 发新命令。下一步不是继续找“恰好能执行”的路径，而是取得该固定开发入口的合法授权/规则归属，或先修复原入口关联。

### 阶段完成再发布一次

只有验证真正的安装布局、skill 发现、发布版本及 Agent 端到端时，才需要本机提交/push → 用户 Studio 发布/安装确认 → adb 新会话验收。开发文档和调试资料始终留在发布内容外。

## 6. 无破坏性操作与收尾证据

本轮前后上述六个已记录 PID/startTicks 未变；以下哈希也未变：

- `/root/.openclaw/openclaw.json`：`27cbfe63b93396a766d8046623386845eec59b64ebd1c28cb9ea4d44a7c459e0`
- `/root/.plugin-adapter-service/config/config.yml`：`5e6e1111519291cbb72ea3fd0670c072037debecaf1bf83aab8f358d1694cc46`
- adapter `dist/main.js`：见上。

这些是窄基线，不是全文件系统无变化证明。本轮未写远端文件、未新建服务监听/隧道或常驻进程。Windows TEMP 留存三个已安装插件的实现源码快照，用于静态读取，不包含配置/凭据；未放进发布内容。仓库新增本报告，未改变发布源码。

## 7. 最小下一步与需平台提供的证据

对已经记录的那次 `exec`，请求宿主维护方提供脱敏的：时间、工具名、tool-call/request/trace 对应、命中的服务/skill/provider 标识、规则或拒绝 reason-code、文案生成层；不要提供 token、完整聊天或原始环境。

优先解决授权归属，不要求用户为了运行离线 `version` 去授权无关的文档业务。若平台提供正式 dev-only 入口/调试模式，再以有界 mock 计划试验一次即可；不需要反复发布插件，也不需要新装原生 tool。
