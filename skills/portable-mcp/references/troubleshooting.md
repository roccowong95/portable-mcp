# 故障排查与边界

| 现象 | 先做什么 |
|---|---|
| 找不到 mcpc | 使用 skill 固定 Python 入口，不假定全局 PATH；显式安装前先确认许可 |
| 找不到 Node/npm | 核实绝对路径；安装器支持 --node / --npm-cli；不自动 sudo/升级系统 |
| .runtime 非空/安装中断 | 不覆盖，检查残留；由用户决定新副本或清理，不删未知路径 |
| bridge 不启动 | 核对 mcpc 版本和平台支持、私有目录权限；不盲目 kill 全部 node 或 restart 他人会话 |
| 新 exec 找不到会话/授权 | 比较 OS 身份、入口、MCPC_HOME_DIR、profile 和后端；勿打印 token |
| 同名会话连错服务器 | 查询会话，核对 URL/profile；批准后关旧会话，或用新名字 |
| 工具不存在/参数错误 | 重新 tools-list / tools-get；不要猜字段、调用不明 fallback |
| grep 退出 1 | 可能只是没匹配，先核对空结果与 stderr，不必触发 OAuth |
| 需要授权 | 先判匿名/header/OAuth；真实登录经用户同意，回调含秘密不能发模型 |
| 断连/超时/非 JSON | 结果未知，不自动重放有副作用调用；本地 timeout 不保证远端取消 |
| 工具说 isError | 错误结果可能包含部分效果；按业务语义确认，不当成功 |

## 不提供的东西

- 不把 MCP 全部工具注册进宿主模型的原生 tools；这是 skill→命令→mcpc 路径。
- 不提供业务权限白名单/沙箱。能用 shell 的 Agent 可能绕过文字限制；生产需系统权限和受控服务入口。
- 不为每个 MCP 生成脚本或说明，schema 来自真实服务。
- 不保证第三方 MCP 的副作用、稳定性、输出可信性或 exactly-once。
- 不修复固定基线所有已知风险。升级/真实 OAuth/并发 token 刷新须独立审核。

## 临时测试清理

只关闭本测试自己建立的会话。确认无用户后使用固定入口 `close @test`，再检查该会话及自己的 bridge/mock 是否退出。不要用 broad pkill；若必须处理残留，先核对 PID、启动时间、完整 argv 和所属独立目录。删除文件前检查绝对路径和保留要求。清理会话不等于撤销 OAuth grant。
