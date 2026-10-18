# 触发能力索引：pmcp-ctl

## 目的与边界

模型选择 skill 时，往往只看名称和 `description`。能力索引让“搜索 Notion 页面”“检索知识库”等任务意图可以命中本 skill，用户不必明确提到 MCP。它不是工具 schema、服务配置、账号映射或授权列表，也不保证宿主一定选择本 skill。

索引放在 `SKILL.md` frontmatter 的 description **内部**，不是独立 YAML 字段：

```yaml
description: >-
  固定通用说明与权限边界（实际文件已有，不要替换成此占位文字）。
  PMCP_CAPABILITIES={"logseq":"检索 Logseq 知识库","notion":"搜索和读取 Notion 页面"}
```

固定说明保留；CLI 只替换最后一行的 JSON，不重排文档、其他 frontmatter 或正文。默认发布包使用空索引 `{}`，不携带你的连接列表。

## 调用

跨平台使用 Python；不要求全局安装 `pmcp-ctl` 或修改 PATH：

```sh
python3 <skill-root>/scripts/pmcp-ctl meta-add notion "搜索和读取 Notion 页面"
python3 <skill-root>/scripts/pmcp-ctl meta-add logseq "检索 Logseq 知识库"
python3 <skill-root>/scripts/pmcp-ctl meta-list
python3 <skill-root>/scripts/pmcp-ctl meta-add notion "搜索、读取和整理 Notion 页面" --dry-run
python3 <skill-root>/scripts/pmcp-ctl meta-rm notion
```

批量同步时，把已确认的条目写进一份本地清单，再一次写入：

```sh
python3 <skill-root>/scripts/pmcp-ctl meta-sync --input ./capabilities.json
python3 <skill-root>/scripts/pmcp-ctl meta-sync --input ./capabilities.json --replace
```

清单可以是对象或数组，同名条目区分大小写：

```json
{
  "notion": "搜索和读取 Notion 页面",
  "logseq": "检索 Logseq 知识库"
}
```

```json
[
  {"name": "notion", "summary": "搜索和读取 Notion 页面"},
  {"name": "logseq", "summary": "检索 Logseq 知识库"}
]
```

默认合并：只新增或更新清单中的条目，其它条目保留。加 `--replace` 时以清单整体替换索引，清单外的条目不保留。清单文件必须是普通文件、不超过 64 KiB，且不能是符号链接；脚本仍不访问网络、MCP 配置或凭据。

Windows 可用已核实的 `python` / Python 绝对路径代替 `python3`。POSIX 用户也可自行给 `scripts/pmcp-ctl` 添加执行权限并使用完整路径直接调用；不需要网络、mcporter runtime 或状态目录。

脚本用 `Path(__file__).resolve().parent.parent / "SKILL.md"` 定位自身 skill，不依赖 cwd、宿主平台、固定用户名或安装目录。整个目录搬迁后继续有效；通过符号链接启动时修改真实脚本旁的 skill，不是链接旁的文档。

| 命令 | 行为 |
|---|---|
| `meta-add NAME DESCRIPTION` | 新增或更新同名能力，大小写有区别 |
| `meta-rm NAME` | 删除指定能力；不存在时无变化，成功返回 |
| `meta-list` | 只读列出当前索引 |
| `meta-sync --input FILE` | 从本地 JSON 清单批量合并；加 `--replace` 时整体替换索引 |
| `--dry-run` | 显示预计结果，不创建锁、不写文件 |
| `--lock-timeout SECONDS` | 等待其他写入者，默认 5 秒，范围 0..60；可设 0 立即失败 |

输出为一行 JSON（非 ASCII 字符以 JSON `\uXXXX` 转义，解析后仍为原文字，兼容旧终端编码）：`capabilities` 是索引；`changed` 表示与当前内容相比是否会变化；`diff` 在 `meta-sync` 时列出 `added`、`updated`、`removed`、`unchanged`，其它命令为 `null`；`written` 只在实际写入时为 true；`dryRun` 表示是否预览。失败返回非零退出码并输出 `PMCP_META_FAILED`。输出不能当成连接成功或授权成功的证明。

## 何时更新

1. 用户批准新增服务，管理员完成必要配置/授权并验证实际能力。
2. 根据已确认的用途，拟定一句简短的**服务级能力摘要**，由用户或管理员确认后运行 `meta-add`；多个服务可写进一份清单，用 `meta-sync` 一次同步。
3. 新会话/宿主重新扫描 skill 后检查触发效果；当前会话可能仍缓存旧 description，CLI 不重启或刷新宿主。
4. 服务不再提供时用 `meta-rm` 避免误路由。实际关闭会话、删除配置、撤销授权是另外的操作，不由本工具执行。

名称只是索引标识，不强制等于 MCP 配置服务名。`@session` 属于旧 mcpc，会话名不是本版标识；本版直接使用精确配置服务名，索引不创建或恢复会话。发布新副本前移除部署特有索引；CLI 不自动扫描配置、连接所有服务、登录、执行工具、拉取描述或修改 OAuth 凭据。

## 输入与安全

- NAME：1..64 个 ASCII 字母、数字、`.`、`_`、`-`，首字符为字母或数字。
- 摘要：1..160 个字符，不允许首尾空白、换行、控制字符、格式字符或保留标记 `PMCP_CAPABILITIES=`；JSON 引号/反斜杠自动转义。
- 最多 24 项，完整 JSON 最多 4096 个 UTF-8 字节。保持简短，过长的 description 可能被宿主截断。
- 不写 token、私有 URL、用户数据、完整 schema、命令或“忽略规则”等指令。**工具不做语义审核或可靠的秘密识别**；不要直接输入未经信任的 MCP 返回说明。索引只用于路由，不扩大工具权限。
- 只支持正式版受控格式 `description: >-` + 非空、两空格缩进的固定描述行 + 最后一行 JSON。遇到单行/quoted YAML、空行后的缩进续行、重复/quoted 顶层 key、缺失/重复 marker、损坏 JSON、重复 JSON key 等会拒绝自动修复；先人工审核。工具校验所支持的 description 布局及顶层 key 边界，不是完整 YAML 解析器；其他字段的值应保留正式版有效格式，不能把一次编辑成功当成任意 YAML 文档合法的证明。

## 写入保护与恢复

协作写入者使用 skill 根目录的 `.pmcp-meta.lock/` 排他锁。取得锁后重新读取、校验，写同目录临时文件并 fsync，确认源文件未变化后原子替换；不改变其余字节，保留 LF/CRLF 和 POSIX mode。相同内容不重写。拒绝符号链接/多硬链接的 `SKILL.md`；POSIX 下拒绝替换其他用户拥有的文件。

锁超时会失败，不自动抢占“陈旧”锁。若进程崩溃，确认没有活跃写入者之后再人工移除空锁目录或遗留 `.pmcp-meta-*.tmp`；不要随意清理其他路径。手工编辑应避免与 CLI 同时进行；非协作写入者仍存在检查后的竞态。本工具不是多用户安全边界或断电持久性保证。

原子替换可能不保留自定义 ACL、扩展属性或安全标签；Windows 使用目录继承 ACL。需要这些属性的部署应在副本上验收/由管理员维护，不要宣称完整权限元数据保留。只读/集中管理的 skill 不应擅自提权修改。CLI 不自动备份含能力摘要的文档；重要自定义先自行留存批准的副本。
