# Amoo 历史 mcpc 入口对照

日期：2026-10-19（Asia/Shanghai，未单独采集该次调用的精确时间）。用户要求核对 Git 历史中的 mcpc 脚本能否通过手机调用。此记录是有限的 help-only 对照，不是旧版 MCP/OAuth 回归。

## 安全边界

- 本机从提交 `3750224` 提取原始 `skills/portable-mcp/scripts/mcpc.py`，同步到服务端独立验证目录。不修改已部署插件，不切换工作树、不安装第三方包。
- 远端通过 Git blob 算法核对内容完全一致：`296c6d7f1ec7b8e5a718684b78844f2f5c9c12f4`；文件 SHA-256：`20eb2df7722603711492b61c3b303125e6f22df3ffb398c763473419648aa3f4`。
- 历史脚本位置：`/root/workspace/portable-mcpc-history-xc6v0386/scripts/mcpc.py`。目录保留复查，不包含 runtime、状态或凭据。
- 仅运行 Python argparse 的 `--help`。源码中该分支在状态目录创建、runtime 检查、Node 或 mcpc 启动之前退出；不连接 MCP、不做授权、不写配置或凭据。
- adb 控制既有设备 `ZYPZ261A01M68R000F2` 的 Amoo 新会话。明确禁止在被拒绝后换入口、软链、复制、改名或改授权策略；不通过旧版继续完成被拒绝的 MCP 工作。

## 对照结果

### A. 未修改的旧 mcpc Python 入口

向 Amoo 请求一次 `exec`：

```sh
python3 /root/workspace/portable-mcpc-history-xc6v0386/scripts/mcpc.py --help
```

手机 UI 中 Amoo 返回与 Git 源码一致的 argparse 文本，包括：

```text
usage: mcpc.py [-h] [--state-dir STATE_DIR] [--node NODE] ...

Stable skill-local entry. Forward argv/stdin/stdout without a shell or
retries.
```

并报告 stderr 为空、退出码 0、未出现授权拦截。Amoo 披露在同一次 exec 中追加 `echo "EXIT_CODE=$?"` 采集退出状态。结果证据来自实际手机会话展示，而非此次额外读取的原始宿主 RPC trace。

### B. 已部署的原始 mcporter Python 入口

在同一新会话中，对已部署入口也只做一次 `--help`，不复制它到验证目录：

```sh
python3 /root/.openclaw/workspace-task/skills/portable-mcp/scripts/mcporter.py --help; echo "EXIT_CODE=$?"
```

Amoo 报告使用 `exec`、其他参数默认。手机出现金山文档授权卡片，工具返回：

> 使用「金山文档」需要先完成OAuth 授权。请提示用户点击对话中的授权卡片完成授权。禁止代用户调用 /v1/oauth/sessions、/v1/auth/sessions 或 client_action 中的接口；不要在对话中索要 Key。用户完成授权后再重试原请求。

没有脚本 stdout/stderr 或退出码。未点击授权，未重试、未换入口。停止本组测试。

## 可得结论与不能推断的内容

- 当前条件下，历史 mcpc **Python wrapper 的帮助命令可经手机调用**；已部署 mcporter 原始路径的同类命令仍被授权拦截。
- 当前 mcporter 的 `main()` 同样先 `parser().parse_args()` 再处理状态/runtime，故 `--help` 不需要执行 Node、加载 mcporter 或访问 vault。这个结果不支持将拦截解释为 mcporter 自身 OAuth 失败或 Node 不兼容。
- 实验仍同时改变了文件路径、脚本内容/文件名与可能的宿主归属元数据，不是仅替换客户端的严格 A/B。因此不能认定“mcporter 包导致问题”，也不能证明只凭名称或路径触发；security-guard 是否为该提示来源仍未证实。
- 没有安装或运行旧 `@apify/mcpc` runtime，没有执行其 version、工具调用或 OAuth，因此未验证旧 mcpc 完整业务链路是否仍正常。
- 不把独立验证目录的成功当作已部署入口获准执行，也不将其用作绕过授权的工作通道。下一步应由宿主侧核对对应两次 `exec` 的授权归属/判定记录，不关闭或修改 guard。
