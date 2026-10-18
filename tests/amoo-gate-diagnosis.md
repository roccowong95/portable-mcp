# Amoo 授权拦截：有界排查结论与 mcpc 条件预案

日期：2026-10-19（Asia/Shanghai）。本轮目标：核对权限、执行身份、宿主元数据与已有日志，尽量定位拒绝层；若证据支持放弃 mcporter，再验证固定 mcpc 文件凭据方案。此记录不宣称已修复授权问题或完成手机 MCP 调用。

相关前序：[架构对照](amoo-architecture-review.md)、[历史 mcpc help 对照](amoo-mcpc-history-comparison.md)、[SSH 技术验证与发布后复测](validation-linux.md)。

## 1. 核对权限和身份

双跳 SSH 对目标脚本及所有祖先逐级检查 owner/mode、可读/遍历、符号链接和 POSIX ACL 是否存在。没有 chmod、chown 或 ACL 修改。

| 对象 | 结果 |
| --- | --- |
| 部署 `scripts/mcporter.py` | UID/GID 0，`0644`，可读，无符号链接，无 POSIX access ACL |
| `/root`、`/root/.openclaw` | `0700`，root 可遍历 |
| workspace-task/skills/portable-mcp/scripts 路径 | `0755`，可遍历，无检测到的 POSIX access ACL |
| 历史独立目录 `scripts/mcpc.py` | `0600`，父验证目录 `0700`，root 可读/遍历；此前手机 help 成功 |
| botagent PID 4288 | real/effective/saved/fs UID 均 0，GID 0；NoNewPrivs 0、Seccomp 0；进程 root 为 `/` |
| adapter PID 4289、OpenClaw PID 4311 | 所检查的 UID/GID 均为 0，进程 root 为 `/` |

部署 mcporter 脚本 SHA-256 仍为 `f8913870691d6391e796b03ce4fa3b65667611d7499cbc36478ea91e8b8d92f1`，历史 mcpc 为 `20eb2df7722603711492b61c3b303125e6f22df3ffb398c763473419648aa3f4`。

**解释**：`python3 script.py` 要求 Python 可执行、脚本可读、祖先目录可遍历，不要求脚本自身带 `+x`。目前不支持“脚本缺执行位”或普通 owner/mode/ACL 拒绝的解释。这是当前进程/文件快照，不能概括为排除了所有远程策略、LSM、容器/账号映射或未来执行环境差异。

## 2. 手机最小诊断：不启动 Python 或 MCP

通过既有 adb 设备 `ZYPZ261A01M68R000F2` 开启 Amoo 新会话，只允许无业务副作用诊断，遇拦截立即停止，不授权或换路径。

### 正控：身份命令

请求 `exec` 执行：

```sh
id -u
```

手机会话回复实际结果为 `0`，报告没有执行其他操作。此证据来自手机会话展示，不是另行采集的原始 RPC trace。

最初 adb 文本输入中包含分号，Android shell 解析导致后续 `id -g` / `command -v python3` 没有进入输入框，工具报 `inaccessible or not found`。核对并补全后的实际发送任务仅为 `id -u`，**不声称手机测得 GID 或 Python 可执行路径**。

### 目标：仅查看文件属性

同会话只请求：

```sh
ls -ld /root/.openclaw/workspace-task/skills/portable-mcp/scripts/mcporter.py
```

Amoo 报告实际工具为 `exec`，其余 workdir/env/timeout/yieldMs/background 均未设置；手机出现授权卡片，返回：

> 使用「金山文档」需要先完成OAuth 授权。请提示用户点击对话中的授权卡片完成授权。禁止代用户调用 /v1/oauth/sessions、/v1/auth/sessions 或 client_action 中的接口；不要在对话中索要 Key。用户完成授权后再重试原请求。

未获得文件属性的 shell stdout 或退出码；没有执行 Python、Node、mcporter、mcpc 或 MCP 服务。没有点击授权、重试或改用其他入口。Amoo 的“误判”推断不是已验证根因，不据此宣称知道匹配规则。

**支持的定位**：同一类宿主拒绝可出现在仅提到目标文件的元数据命令上，不依赖 mcporter 包被加载。它不是一个客户端 OAuth 回调/刷新失败的证据。`id -u` 正控说明 exec 并非对所有命令普遍不可用；仍不足以证明只按路径/名称匹配。

## 3. 安装元数据与日志：能看见什么

- 部署 skill 的 origin 指向 portable-mcp 的带 hash slug，安装版本 `0.6.0`；安装时间与同目录记录一致。仅提取相关非凭据字段，没有访问 registry 鉴权或发 registry API 请求。
- workspace 的 `.clawhub/lock.json` 有 `portable-mcp` 和同一带 hash slug 两个键，均为版本 `0.6.0`、`installedAt=1792347802174`。这可能是规范名与完整 slug 的双别名，**同版本/同时间不是已证实的元数据冲突**。所读的相关索引没有给出金山文档 provider/rule 的映射；不能据此清理或改写索引。
- botagent 当日日志具有 `builtin.tool.call`、`stepclaw.agent.skill.paths`、`stepclaw.hook.dispatch` 方法记录。现有受限输出不足以把目标拒绝与精确 request/session、工具参数及服务/rule/provider 关联起来；没有可据以归因的 `permission denied` 或该中文拒绝文本。
- security-guard 的存在、before hook 和远程裁决代码已经在前序报告核实，但既有日志、文案前缀差异及源码阴性搜索不构成其导致本次提示的证明。ability-params-inject 的已读内容也没有提供目标提示的明确映射。
- 只按元数据分析有限日志，不复制原始聊天、进程参数、环境或 token。没有新增 trace/debug、抓包、RPC 重放、改配置、停插件、清缓存或请求业务授权。

## 4. 当前决定：不因本次拦截直接回归 mcpc

**已验证**：mcporter 在当前服务 Node 环境经 SSH 能运行，真实 0.9.0 加本地 fixture 的工具发现/schema/调用已通过。手机原部署路径在执行前受阻，甚至 `ls -ld` 也受阻。历史 mcpc 仅在独立路径验证过 Python help。

**不能推出**：mcporter 客户端在手机执行后失败、mcpc runtime 已经通过手机 MCP 调用，或者改回 mcpc 就能解决宿主授权。help 对照同时改变路径、脚本内容/文件名和可能的归属，不是 engine-only A/B。

因此，用户所设“确定回归后，先跑通运行端和手机，再提交 mcpc 分支”的条件尚无足够依据触发。本轮不安装 mcpc、不恢复旧透传入口、不迁移凭据、不建立一个可绕过现有拒绝的工作通道，也不创建未经验证的 `mcpc` 分支。**这是有界调查的证据终点，不是问题已经解决。**

继续定位需要宿主提供对应拒绝的脱敏裁决关联：时间、tool-call/request ID、服务/skill/provider/rule 标识、reason-code、文案生成层及命中参数类别。不要提供 token 或完整聊天。优先核查这个授权归属；不要为离线 version 或文件属性检查去授权无关文档业务。已有日志不足时，新观察手段应先明确窗口、最小字段和权限边界，不能通过关 guard 验证。

## 5. mcpc 条件预案：仅完成静态调研，未执行

固定 `@apify/mcpc@0.7.0` 可以通过已审计的 keychain 探测改动强制其内建 file fallback，但仅恢复历史三个脚本不满足当前固定部署与安全约定。

若后续决定做独立原型，最小合同为：

1. 单独 `.runtime/mcpc`，固定 0.7.0 **及已审计依赖 lock/integrity**，现有 Node（该版本基线 >=22.12.0），不升级系统 Node，不覆盖 mcporter 或旧状态。
2. 保留有限命令、固定私有账号状态、环境清理、profile/runtime OS 锁；不恢复任意 native argv、state-dir、node 或自动业务失败 fallback。
3. `init` 在锁内验证包版本与原始 keychain 文件的原始字节 SHA-256，按唯一已审计转换安全写入并复验，完成后才写 ready 标识；缺 runtime 时只要求显式安装，不下载。重复 init 应幂等，未知 hash、链接、多硬链、权限异常均失败关闭。
4. 后续每次操作必须重新验证已打补丁的 hash，不能仅信 marker；包更新与使用协调锁。已启动 bridge 不会因磁盘改动而切换 backend，新操作必须从补丁后的代码启动。
5. 不读/迁移真实 keyring 或 token。使用内建明文 file fallback，目录/文件权限保护不抵御 root/同 UID；损坏 JSON 必须保留并拒绝，不把读错当凭据不存在。避免 host/profile 与完整 endpoint 的映射碰撞。
6. 固定版已知 OAuth callback-state 缺口仍存在，真实授权默认不可用，另行修复审计前不放开。SDK 401 可能刷新并重发，单次 wrapper 不保证网络/业务 exactly-once；文件写锁也不等于整个 refresh 事务锁。

审计补丁把 `ensureProbed()` 固定为 `keychainAvailable = false`。历史可复验 digest：

| 状态 | SHA-256 |
| --- | --- |
| 原始 | `347235ccd693c74325fb37b49ec29a0b73128cc2d9c2cd42e55dd2ec18d93762` |
| 补丁后 | `51fac25726f5d15a78882780bc657cdac13831e1b847b324b85394342370829c` |

安装包验 hash 必须对原始字节，不能通过换行归一化接受未知漂移。该补丁不修复非原子落盘、回调 state、刷新竞态或 keychain-only wallet API。

真正选择分支前需另跑：hash/版本/重复 init/并发安装使用/中断/篡改/权限和毒化环境；实际 keychain 模块配 native sentinel 的假凭据跨进程 CRUD；真实 pinned mcpc 加本地 fixture 的动态发现/schema/精确调用/isError/回执与清理；最后一个正常获准的手机 fixture（exec 与 botagent 祖先、nonce、结果 digest、独立服务回执关联）。遇同类宿主拒绝停止，不能复制或改名绕行。**现有 mcporter 17/35/5 测试数字不适用于此预案。**

## 6. 改动、残留与收尾

- 发布 `src/` 未改变；新增内容仅为仓库开发报告和只读权限诊断脚本。
- 没有新建远端 runtime、配置、凭据、服务或监听。前序历史 help 目录及 Windows TEMP 源码/UI 证据留存，未提交运行时、截图或凭据。
- 本轮手机只做已列出的身份和文件属性探针；正常访问可产生宿主日志和会话记录。前序测试产生的假凭据不在本轮重新使用。
- 结束时六个进程 PID/startTicks 仍为：96/82、1056/445337、4288/5430039、4289/5430039、4311/5430066、31755/11181733。
- `/root/.openclaw/openclaw.json` SHA-256 仍为 `27cbfe63b93396a766d8046623386845eec59b64ebd1c28cb9ea4d44a7c459e0`；adapter config 仍为 `5e6e1111519291cbb72ea3fd0670c072037debecaf1bf83aab8f358d1694cc46`；adapter bundle 仍为 `b9624b4c18406c8246be7412631fcb973bffe078572cd0f006b932c0366ced0f`。

这些窄基线支持没有替换所列配置或重启所列进程，不是全盘无变化或强安全隔离证明。
