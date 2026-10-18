# 版本与官方资料

本 skill 的可执行基线固定 `@apify/mcpc@0.7.0`；这是已研究/测试版本，不是“永远使用最新”或安全认证。

- 项目与 README：[apify/mcp-cli](https://github.com/apify/mcp-cli)（CLI 名称 mcpc）。
- npm 包：[ @apify/mcpc ](https://www.npmjs.com/package/@apify/mcpc)。
- MCP 协议与工具定义：[modelcontextprotocol.io](https://modelcontextprotocol.io/specification/latest)。
- 认证标准：[MCP authorization](https://modelcontextprotocol.io/specification/latest/basic/authorization)。

官网/main 文档可能属于新版本，不能代替安装版本的 `--help`/源码。先核对本地：

```text
mcpc --version
mcpc --help
mcpc connect --help
mcpc login --help
mcpc @session tools-call --help
```

已知基线事项：

- `login` 无经过验证的 `--code` 两阶段入口；无浏览器时可有 stdin callback 流程，依赖原进程存活。
- 回调 state、本地文件凭据、并发刷新和 SDK 401 重试风险见认证文档。成功登录/发现不等于这些风险已解决。
- 安装 runtime 与自己的 MCP 配置相互独立，不自动导入 OpenClaw 或其他宿主私有配置。
- 版本更换后重新验证命令、输出 shape、stdio/HTTP、错误和清理；不要把 0.7.0 的源码补丁套到新版本。
