# 环境检查与显式安装

## 1. 固定前提，不升级系统 Node

MCP 业务需要 Python 3.9+、现有 PATH 中的 Node/npm；仅维护本 skill description 的 `pmcp.py meta-*` 只需 Python，无需 runtime、Node、npm 或 init，不访问账号状态或 MCP，详见[能力索引](capability-index.md)。portable-mcp 不安装或升级 Node，不写系统包、全局 npm 或 shell profile，不提供路径、Node/npm、registry、版本、超时选项或部署环境覆盖。缺少前提就停止并报告，不换全局 CLI、浮动 npx 或其他 Node 绕过。

业务入口是 `python3 <skill-root>/scripts/pmcp.py`。内部依赖真实 npm 包 `mcporter`；插件命名不改变依赖来源、Node engines、安全门槛或版本差异。

## 2. 安装检查、安装与更新

下列 `/actual/skill` 是实际 skill 安装位置的占位符，不是状态路径选项。安装/更新下载第三方代码前须得到许可；检查可能访问淘宝镜像元数据，但不安装或写运行时。

```sh
# 检查/选择；已有安装时默认离线校验并复用
python3 /actual/skill/scripts/install_runtime.py --check
# 获得许可后显式安装，业务调用不会代做
python3 /actual/skill/scripts/install_runtime.py
# 查询更新候选；仅 --update 才重新选择版本
python3 /actual/skill/scripts/install_runtime.py --update --check
# 明确批准更新后才执行
python3 /actual/skill/scripts/install_runtime.py --update
```

首次显式安装固定使用淘宝镜像 `https://registry.npmmirror.com/` 获取完整元数据及安装包；这是**第三方镜像，不是 npm 官方源**。以现有 npm 自带 semver 选择稳定、未 deprecated、`>=0.9.0` 且根包 `engines.node` 匹配现有 Node 的最高版本。镜像失败即报告错误，不静默 fallback 到官方源。不能指定版本、镜像或 npm 配置；`dist-tags.latest` 不是兼容性证明。已有兼容安装默认离线校验并复用，不因更换固定镜像而强制更新。

`mcporter 0.9.0` 根包要求 Node `>=20.11.0`，`0.15.0` 要求 `>=24`。0.9 只是兼容性示例，不是要求安装的版本。**根包匹配不等于依赖满足**：安装用 `--engine-strict --ignore-scripts --save-exact --no-audit --no-fund`、私有 npm 配置/缓存和 package-lock 校验依赖。依赖引擎不兼容就停止，不 force、不忽略 engines、不升级 Node。未来上游 API 不兼容也失败关闭，见[版本来源](sources.md)。

安装成功后锁定精确版本并复用，不每次追逐最新版。安装器只暴露 `--check`、`--update`。内部记录/lock 用于核对安装，不得手工伪造；`--ignore-scripts` 仅禁止安装生命周期脚本，不证明包安全，也可能令依赖功能不可用，不能为通过安装擅自开脚本或改 lockfile。只读 skill 需管理员在批准的可写副本预装，不擅自提权。

## 3. 固定新状态布局与保留的运行时

配置固定在 **OS 账号真实 home 下的 `.pmcp/config/mcp.json`**。POSIX 通过 `pwd.getpwuid` 定位，Windows 通过系统 profile 定位，忽略环境 HOME/USERPROFILE。所有操作保持同一机器、同一 OS 账号；内部目录不让用户选择。

```text
<skill-root>/scripts/
  install_runtime.py        # 用户许可后显式安装/更新
  runtime_versions.cjs      # 利用 npm 自带 semver 检查 Node engines
  pmcp.py                   # 统一业务与本地 meta-* 入口，不透传原生 CLI
  mcp_bridge.mjs            # 内部发现/精确调用，禁止自动 OAuth
  .runtime/mcporter/        # 兼容保留：运行时、lock、安装记录，不分发
<OS账号真实home>/.pmcp/
  config/mcp.json           # 唯一配置，mcpServers + imports: []
  home/                    # 内部 HOME/USERPROFILE
  data/                    # 内部 XDG_DATA_HOME
  cache/                   # 内部 XDG_CACHE_HOME
  state/                   # 内部 XDG_STATE_HOME
  broker/                  # 内部 daemon 路径；本版不启动 daemon
  .pmcp.lock               # 全 profile OS 锁
```

这些路径用于解释隔离和排错，不是可选部署参数。状态改用 `.pmcp`，配置改用 `config/mcp.json`；**不自动导入、迁移或复制旧状态/凭据，旧 `.portable-mcp` 保持原样**。新部署须显式 init、经批准重新配置。运行时暂仍为 `scripts/.runtime/mcporter`，上游内部 vault 命名也未改，不宣称完整文件名整理。内部 HOME/USERPROFILE、XDG config/data/cache/state 与 daemon 环境隔离运行状态，但这些变量不参与真实 home 的状态根定位。stdio 子进程会受私有 HOME 影响，详见[MCP 配置](mcp-configuration.md)。

## 4. 初始化与业务检查

```sh
python3 /actual/skill/scripts/pmcp.py init
# 替换为已批准的端点；.invalid 仅为占位符
python3 /actual/skill/scripts/pmcp.py config-add docs --url https://mcp.example.invalid/mcp --dry-run
python3 /actual/skill/scripts/pmcp.py config-add docs --url https://mcp.example.invalid/mcp
python3 /actual/skill/scripts/pmcp.py version
python3 /actual/skill/scripts/pmcp.py servers
python3 /actual/skill/scripts/pmcp.py doctor
```

`init` 无需 runtime，生成固定空配置且不覆盖已有内容、不导入旧状态。**Agent 新增服务必须用 `config-add`，不能手工编辑 JSON**；包括 dry-run 在内都需显式 init、已安装运行时和 Node。同名拒绝，无 replace/remove；未支持高级字段时暂停协调。包装器锁内用私有临时 JSON 调用原生 config add，补 ephemeral/cwd，验证 imports 和现有条目、校验后原子发布；不联网/MCP/启动配置的 stdio/OAuth。env/header 值仅环境引用，command/args 禁止秘密，完整 HTTP(S) URL 支持批准的 token/其他 query 并原样交给 backend，仍拒绝 userinfo/fragment/空白/反斜杠和无效协议/host/port；含凭据 URL 仅落私有配置、不进 skill/能力索引/示例/回复/日志，原生 CLI 的 argv 仍可见。完整选项见[MCP 配置](mcp-configuration.md)。其余业务操作要求有效配置与安装记录；`meta-*` 不受此要求影响，不读取或创建账号状态。`version` 的 JSON 为 `{"backend":{"package":"mcporter","version":"实际安装版本"},"node":"实际 Node 可执行文件路径"}`；`doctor` 同样通过 `backend: {package, version}` 标识依赖，并以 `nodeVersion` 报告实际 Node 版本。离线检查不是联网、授权或业务成功的证明。

配置根 key 仅 `mcpServers` / `imports`，imports 明确为 []，每个服务显式 lifecycle ephemeral；所有业务命令（包括 auth）先校验，不自动改写配置。配置业务 env 不得覆盖隔离/控制变量。不传旧 `--` 分隔符、原生 JSON 开关、@session 或 connect 参数。

内部固定等待策略：普通 MCP timeout 60 秒、父进程总上限 65 秒；auth/logout 父进程上限 605 秒（600 秒预算 + 5 秒清理），不向原生 CLI 传入该预算，后端可能更早结束；profile 锁等待 30 秒。无用户参数或环境覆盖。超时不保证远端取消，不为绕过 busy 换目录/账号/客户端，不自动重放。

POSIX 新目录 0700、文件 0600，拒绝不私有、错误所有者及链接状态，不擅自 chmod 既有目录。Windows 由管理员预设受保护 ACL，入口只验证，不自动改 ACL；Linux 为主要目标，不承诺完整 Windows 生产验收。权限不是加密或沙箱，不防 root/同权限进程。

业务的全 profile 操作由 OS 锁串行化；meta 命令只使用 skill 内的索引写入锁。旧版非原子 vault 写入仍可能因崩溃损坏，失败关闭、不自动修复。不得让原生 CLI 或其他客户端并发复用 vault。

## 5. 生命周期与分发边界

只支持 ephemeral，每个服务必须显式 `"lifecycle": "ephemeral"`。联网业务命令各自创建并关闭连接，meta 命令不连接 MCP；不保留 @session，不启动 keepalive/daemon/serve/generate，不支持跨命令订阅。内部 broker 路径只是防止误用默认命名空间，不表示后台进程功能已启用。

分发仅复制源码，排除运行时、node_modules、安装生成的 lock/cache、私有配置、状态、日志、凭据与部署特有能力索引。更新遗留的 stage/backup 目录，仅在核对确切绝对路径、无人使用及用户许可后处理，不删除未知目录或旧运行时。不导入/迁移/复制旧状态或 token，见[私有存储与旧状态边界](file-storage.md)。安装选择、离线检查、宿主集成、真实授权与过期刷新分别验证，不互相替代。
