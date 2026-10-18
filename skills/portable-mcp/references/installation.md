# 显式安装与固定入口

## 1. 布局与前提

```text
<skill-root>/
  SKILL.md
  references/
  examples/mcp.example.json
  scripts/
    install_mcporter.py       # 显式安装/更新，不由调用入口触发
    mcporter_versions.cjs     # 使用 npm 自带 semver 判断版本/Node engines
    mcporter.py               # 有限的稳定命令集，不透传原生 CLI
    mcporter_bridge.mjs       # 精确发现/调用，禁止自动 OAuth
    pmcp-ctl                  # 仅维护 description 能力索引
    .runtime/mcporter/        # 私有包、lock、安装记录，不提交/分发
<private-state>/              # 必须是 skill 外的绝对路径
  config/mcporter.json        # 唯一服务配置：mcpServers + imports: []
  home/                      # HOME / USERPROFILE
  data/                      # XDG_DATA_HOME
  cache/                     # XDG_CACHE_HOME
  state/                     # XDG_STATE_HOME
  broker/                    # MCPORTER_DAEMON_DIR；本版不启动 daemon
  .pmcp.lock                 # 全目录 OS 排他锁
```

需要 Python 3.9+、**现有** Node 和 npm，不自动安装或升级 Node，不写系统包、全局 npm 或 shell profile。只读 skill 部署需管理员在批准的可写副本预装，不擅自提权。Linux 远端为主要目标；Windows 支持次要，不意味着已完成全部生产 ACL/子进程验收。

## 2. 版本选择，不是任意 latest 保证

首次安装读取已配置 HTTPS npm registry 的完整 `mcporter` 元数据，借助该 npm 自带的 semver 选出：稳定、未 deprecated、`>=0.9.0`、根包 `engines.node` 匹配实际 Node 的最高版本。未来符合条件的发布也参与选择，不硬钉 0.15.0，也不把 `dist-tags.latest` 当兼容性证明。

官方发布元数据中，0.9.0 的根包要求 Node `>=20.11.0`，0.15.0 要求 `>=24`。**这些只是根包条件**：依赖随解析结果变化，根包匹配不等于可安装/可运行。安装使用 `--engine-strict --ignore-scripts --save-exact --no-audit --no-fund`、独立 npm 配置/缓存和 package-lock；依赖不兼容即失败，不 `--force`、不忽略 engines、不改系统 Node。安装成功也不代表所有业务、OAuth 或未来上游 API 已验收；来源见[版本资料](sources.md)。

默认 registry 用现有 npm 的 `config get registry` 只读取得（通常为官方 `https://registry.npmjs.org`），不是固定镜像。可显式 `--registry https://registry.npmjs.org`；仅接受 HTTPS，不在 URL 中放用户名、token、query 或 fragment。

## 3. 显式选择、安装和更新

以下 POSIX 命令均为路径占位示例，执行下载前须得到许可；不在普通 MCP 调用中执行安装。

```sh
# 只选择/检查，不安装、不写入；仍可能读取 registry 元数据
python3 /actual/skill/scripts/install_mcporter.py --check
# 明确指定既有 Node/npm 路径，不调用 npm.cmd 或拼接 shell
python3 /actual/skill/scripts/install_mcporter.py \
  --node /absolute/bin/node --npm-cli /absolute/npm/bin/npm-cli.js \
  --registry https://registry.npmjs.org
# 管理员确需固定候选版本时；仍校验稳定性、deprecated、最低基线和 Node
python3 /actual/skill/scripts/install_mcporter.py --version 0.9.0 --check
```

已存在完整有效安装时，默认离线验证并复用，不重新选择最新版。更新须明确批准：

```sh
python3 /actual/skill/scripts/install_mcporter.py --update --check
python3 /actual/skill/scripts/install_mcporter.py --update
```

安装到 `scripts/.runtime/mcporter/`，包为 `node_modules/mcporter`，CLI 为 `dist/cli.js`；`skill-install.json` 记录精确版本、Node/npm 路径等供入口核对。不得手工伪造/改 marker 让未完成安装通过。更新采用独立 stage 并保留旧副本备份；可能留下 `.runtime/.mcporter-stage-*` / `.mcporter-backup-*`，检查明确绝对路径、无人使用并获准后再清理，不删未知目录。旧 mcpc `.runtime/` 内容不被自动删除或覆盖。

`--ignore-scripts` 只禁止安装生命周期脚本，不等于下载包无恶意，也可能使依赖功能不可用。不要为通过安装擅自开启脚本或修改 lockfile。Windows 可用现有 Python/Node 的绝对路径；不因 PATH 有 Node 就宣称平台已验收。

## 4. 初始化与所有调用共用的状态

```sh
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp init
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp version
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp servers
python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp doctor
```

`init` 不需要已安装 runtime，创建空的 `config/mcporter.json`，不覆盖已有配置。其余命令先要求有效配置及安装记录。可用 `PMCP_STATE_DIR` 设目录，但固定 `--state-dir` 更不易在新 SSH/exec 中丢失；旧 `MCPC_HOME_DIR` 不使用。

后续文档中 `pmcp` 是 `python3 /actual/skill/scripts/mcporter.py --state-dir /absolute/private/pmcp` 的简写，**不是要求创建全局 alias**。`--node /absolute/bin/node`、`--timeout 60000`（毫秒）、`--lock-timeout 30`（秒）放在子命令前。不沿用旧入口的 `--` 分隔符；不传原生 `--json`、`@session`、connect 等参数。

配置根 key 仅 `mcpServers` / `imports`，imports 明确为 []，每个服务显式生命周期 ephemeral；所有命令（包括 auth）先校验，不自动改写配置。

入口设置私有 HOME/USERPROFILE、XDG config/data/cache/state 及 MCPORTER_DAEMON_DIR，并清除继承的 mcporter/相关控制变量，配置固定为 `config/mcporter.json`。POSIX 新目录 0700、文件 0600，拒绝明显不私有、错误所有者及链接状态；不擅自 chmod 既有目录。Windows 需管理员预建受保护 ACL，入口只验证、不自动改 ACL。目录权限不是加密或沙箱，不防 root/同权限进程。

同一状态目录的全部入口命令由 OS 锁串行化，串行化旧版 vault 读改写事务；旧 0.9 非原子写入崩溃风险仍在，损坏时失败关闭，不自动修复。忙时等待至 lock timeout 后失败，不绕过锁、不自动重放。不要让原生 CLI、其他客户端或另一个入口同时写这个 vault。

## 5. 第一版生命周期与分发

只支持 ephemeral，每个服务必须显式 `"lifecycle": "ephemeral"`，不依赖名称推断默认值。每次发现/调用创建并关闭连接；不保留 `@session`、不启动后台 keepalive。keep-alive/daemon/serve/generate 被拒绝，私有 broker 路径只是防止误用默认命名空间，不是 daemon 能力。旧计划中的持久会话、订阅、后台进程所有权及退出策略延期单独设计验证。

分发仅复制源码，排除 `.runtime/`、node_modules、lock/cache 生成物、私有配置、状态、日志、凭据与部署能力索引。迁移不带 token，见[迁移指南](file-storage.md)。最终应用测试按[仓库约定](../../../AGENTS.md)：**commit 并 push → 用户手动安装 → adb 启动 Amoo 助手 → 开启新会话测试**；提交前不执行测试。
