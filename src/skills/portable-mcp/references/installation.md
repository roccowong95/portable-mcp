# 固定部署与显式安装

## 1. 不提供部署选择

需要 Python 3.9+、现有 PATH 中的 Node/npm。入口不安装或升级 Node，不写系统包、全局 npm 或 shell profile，不提供路径、Node/npm、registry、版本、超时选项或环境覆盖。缺少前提就停止并报告，不换全局 mcporter、浮动 npx 或其他 Node 绕过。

服务配置固定在 **OS 账号真实 home 下的 `.portable-mcp/config/mcporter.json`**。POSIX 通过 `pwd.getpwuid` 定位，Windows 通过系统 profile 定位，忽略环境 HOME/USERPROFILE；改变环境不切换 profile。内部目录也由入口固定管理，不让用户选择。所有操作保持同一机器、同一 OS 账号。

```text
<skill-root>/scripts/
  install_mcporter.py       # 用户许可后显式安装/更新
  mcporter_versions.cjs     # npm 自带 semver 检查 Node engines
  mcporter.py               # 有限业务命令，不透传原生 CLI
  mcporter_bridge.mjs       # 发现/精确调用，禁止自动 OAuth
  pmcp-ctl                  # description 能力索引
  .runtime/mcporter/        # 内部运行时、lock、安装记录，不分发
<OS账号真实home>/.portable-mcp/
  config/mcporter.json      # 唯一服务配置：mcpServers + imports: []
  home/                    # 内部 HOME/USERPROFILE
  data/                    # 内部 XDG_DATA_HOME
  cache/                   # 内部 XDG_CACHE_HOME
  state/                   # 内部 XDG_STATE_HOME
  broker/                  # 内部 daemon 路径；本版不启动 daemon
  .pmcp.lock               # 全 profile OS 锁
```

这些路径用于解释隔离/排错，不是可选部署参数。旧自选状态目录不会自动迁移或导入凭据。只读 skill 需管理员在批准的可写副本预装，不擅自提权。Linux 远端为主要目标，Windows 次要，不代表完成全部生产 ACL/子进程验收。

## 2. 自动选兼容版本，不保证任意 latest

首次显式安装固定读取官方 `https://registry.npmjs.org` 完整元数据，以现有 npm 自带 semver 选择稳定、未 deprecated、`>=0.9.0` 且根包 `engines.node` 匹配现有 Node 的最高版本。无需也不能指定版本、镜像或 npm 配置；不把 `dist-tags.latest` 当兼容性证明。

官方 0.9.0 的根包要求 Node `>=20.11.0`，0.15.0 要求 `>=24`。**0.9 只是兼容性示例，不要求安装它；根包匹配不等于依赖满足。** 安装内部使用 `--engine-strict --ignore-scripts --save-exact --no-audit --no-fund`、私有 npm 配置/缓存和 package-lock。依赖引擎不兼容就停止，不 force、不忽略 engines、不改系统 Node。未来上游 API 不兼容也失败关闭；来源见[版本资料](sources.md)。

## 3. 只有显式检查、安装和更新

下列 `/actual/skill` 替换为实际 skill 安装位置，不是状态路径选项；下载第三方代码前须得到许可。

```sh
# 只检查/选择，不安装、不写运行时；初次可能读取官方元数据
python3 /actual/skill/scripts/install_mcporter.py --check
# 显式安装；业务调用不会代做
python3 /actual/skill/scripts/install_mcporter.py
# 已有安装默认离线校验并复用；仅更新才重新选择
python3 /actual/skill/scripts/install_mcporter.py --update --check
python3 /actual/skill/scripts/install_mcporter.py --update
```

完成安装后锁定精确版本并复用，不每次追逐最新版。安装器只暴露 `--check` 和 `--update`，不暴露部署参数。内部记录/lock 用于核对完整安装，不得手工伪造；更新的 stage/backup 目录仅在确认确切路径、无人使用及许可后清理，不删除未知目录。旧 mcpc 运行时不自动删除。

`--ignore-scripts` 仅禁止安装生命周期脚本，不证明包安全，也可能令依赖功能不可用。不能为通过安装擅自开脚本或改 lockfile。PATH 缺少 Node/npm 时报告前提缺失，不由 skill 改系统环境或选择另一套工具链。

## 4. 初始化与固定业务入口

```sh
python3 /actual/skill/scripts/mcporter.py init
python3 /actual/skill/scripts/mcporter.py version
python3 /actual/skill/scripts/mcporter.py servers
python3 /actual/skill/scripts/mcporter.py doctor
```

`init` 无需 runtime，生成固定配置且不覆盖已有内容。其余操作要求有效配置与安装记录。后续 `pmcp` 仅是 `python3 /actual/skill/scripts/mcporter.py` 的简写，不要求创建全局 alias。不传旧 `--` 分隔符、原生 JSON 开关、@session 或 connect 等参数。

配置根 key 仅 `mcpServers` / `imports`，imports 明确为 []，每个服务显式 lifecycle ephemeral；所有命令（包括 auth）先校验，不自动改写配置。内部私有 HOME/USERPROFILE、XDG config/data/cache/state 与 daemon 环境隔离运行状态；配置业务 env 不得覆盖隔离/控制变量。这些子进程变量不参与真实 home 的状态根定位。

内部固定策略：普通 MCP timeout 60 秒，父进程总上限 65 秒；auth/logout 父进程上限 605 秒（600 秒预算加 5 秒清理窗口），不向原生 CLI 传入该预算，后端可能更早结束，不保证授权等待恰好 600 秒；profile 锁等待 30 秒。没有用户参数或环境覆盖。超时不保证远端取消，不为绕过 busy 换目录/账号/客户端，不自动重放。

POSIX 新目录 0700、文件 0600，拒绝不私有、错误所有者及链接状态，不擅自 chmod 既有目录。Windows 由管理员预设受保护 ACL，入口只验证、不自动改 ACL；不承诺完整生产验收。权限不是加密或沙箱，不防 root/同权限进程。

全 profile 操作由 OS 锁串行化；旧 0.9 非原子 vault 写入仍可能因崩溃损坏，失败关闭、不自动修复。不得让原生 CLI 或其他客户端并发复用 vault。

## 5. 生命周期、分发与验收

只支持 ephemeral，每个服务必须显式 `"lifecycle": "ephemeral"`。每次连接后关闭，不保留 @session，不启动 keepalive/daemon/serve/generate。内部 broker 路径只是防止误用默认命名空间；旧持久会话、订阅、后台进程所有权和退出策略延期单独设计验证。

分发仅复制源码，排除运行时、node_modules、lock/cache 生成物、私有配置、状态、日志、凭据与部署能力索引；迁移不带 token，见[迁移指南](file-storage.md)。安装选择、离线检查、宿主集成、真实授权与过期刷新分别验证，不互相替代。
