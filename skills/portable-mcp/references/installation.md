# 安装和运行 mcpc

## 1. 约定的目录

```text
<skill-root>/
  SKILL.md
  references/                # 按需读取的说明
  scripts/
    install_mcpc.py          # 显式安装，不在调用时自动运行
    mcpc.py                  # 固定入口，转发 stdin/argv，不做自动重试
    force_file_store.py      # 可选，本地文件凭据补丁
    .runtime/               # 自动生成的包、lock、缓存；不打包、不提交
<private-state>/             # 在 skill 外：会话、profile、日志，可能含凭据
<private-config>/mcp.json    # 在 skill 外：服务连接配置
```

这种布局适用于 Agent 有文件读取/命令执行能力、skill 目录可写的环境。只读/集中管理的 skill 不强行改权限，改用管理员预装入口。运行时依赖与发布源码分开，私有状态始终在 skill 外，避免复制 skill 时携带 token。

## 2. 前提与授权

- Python 3.9+、Node.js >=22.12.0、npm。无需 OpenClaw、Stepx 或宿主 MCP 连接器。
- 当前基线锁定 `@apify/mcpc@0.7.0`，不意味着最新、安全认证或支持所有平台。
- 安装会下载第三方代码；须先获得用户许可。安装脚本使用 `--ignore-scripts --save-exact --no-audit --no-fund`，保留 package-lock；这不等于完整供应链验证或可在未验证平台使用。
- Linux 已做过 CLI/持久 bridge 测试；Windows 原生 bridge/ACL、macOS keychain 不由此保证。原生不支持时选用户批准的 Linux/WSL/远端环境，不偷偷换执行位置。

先检查实际 Python、Node/npm。不要把另一个同名工具 mcporter 的参数套进来。

## 3. 显式安装

POSIX 示例（将路径替换成实际 skill 根目录）：

```sh
python3 /actual/skill/scripts/install_mcpc.py
```

若 Node 不在 PATH，可指定已核实的可执行文件；找不到 npm 时可指定 npm-cli.js：

```sh
python3 /actual/skill/scripts/install_mcpc.py \
  --node /actual/node --npm-cli /actual/npm/bin/npm-cli.js
```

脚本不会写全局 npm 安装，不会修改 shell profile，不连接任何 MCP，不运行真实 OAuth。默认从淘宝 npm 镜像 `https://registry.npmmirror.com` 下载固定版本；需要其它源时用 `--registry https://...` 指定，脚本只接受 https 地址。只接受空 `.runtime/` 或验证已完成的同版本安装；安装失败可能留下非空目录，应检查后由用户批准清理/换副本，不盲目覆盖。升级须重新审核，不运行浮动 `npx @latest`。

Windows 可用已安装 Python 的绝对路径；脚本支持以 Node 执行 npm-cli.js，避免 `.cmd`/shell 拼接。Windows PATH 中的 Node/npm 不代表后台 bridge 已受支持。

## 4. 固定入口和私有状态

```sh
python3 /actual/skill/scripts/mcpc.py \
  --state-dir /absolute/private/mcpc-state -- --version
python3 /actual/skill/scripts/mcpc.py \
  --state-dir /absolute/private/mcpc-state -- --json
```

下文所有 `mcpc …` 都是此完整前缀的简写。也可设置 `MCPC_HOME_DIR` 后省略 `--state-dir`，但固定参数较不容易在新 SSH/exec 中丢失。必要时 `--node /absolute/path/node` 放在 `--` 之前。

入口会校验包版本、创建状态目录（POSIX 0700）并拒绝明显的非私有权限和 skill 内状态；不会擅自 chmod 现有目录。Windows ACL 必须由管理员设置。不是多租户沙箱，也不能阻止同权限/root 读取。

**登录、连接、发现、调用要保持同一身份、入口、状态目录和 profile。** 新 SSH 不自动继承上次 export；不要改入口后宣称已有 token 可用。

状态目录不是 MCP 连接配置，也不一定包含 token：OS keyring 的 host/profile 命名可能跨状态目录共享。真实 OAuth 前读 [authentication.md](authentication.md)。如需强制文件后端，需单独批准 [file-storage.md](file-storage.md) 的版本绑定补丁；安装脚本不自动打补丁。

## 5. 验收和分发

1. `--version`、`--help` 成功。
2. 只连接一台已批准服务，`tools-list` / `tools-get` 获取实际 schema。
3. 用户允许的低风险调用，通过 JSON stdin 提交，检查结果语义。
4. 用新的 exec/SSH 重复发现，验证状态/必要授权持久性；OAuth 刷新另行验收。
5. 临时会话结束后 `close`；不是撤权或删除凭据。

分发只复制 skill 源文件，排除 `.runtime/`、`node_modules/`、缓存、私有配置/状态/日志及凭据。新增 MCP 通常只改外部配置与连接，不改 skill。转移安装后的 skill 可能让旧 bridge 的代码路径失效；先确认无人使用，关闭其会话，在新位置重新安装/连接，不搬运 token。
