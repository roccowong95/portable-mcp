# 可选：强制 mcpc 0.7.0 使用文件凭据

## 何时需要

无桌面服务器的 OS keyring 可能退到仅进程内存；同进程登录成功，新 SSH 却找不到 token。`MCPC_HOME_DIR` 本身不能强制文件后端，也不是 keyring 命名空间。

优先按官方支持的平台部署；若用户明确选择文件保存，本 skill 附带**版本/源码 SHA 绑定的本地补丁**，只修改独立 mcpc 副本中 keychain 的探测函数，使其使用已有 credentials.json fallback。不是官方 CLI flag，不修复 OAuth state/并发刷新问题，不迁移任何已有秘密。

## 执行前

- 获得修改此独立副本的许可；停止使用它的会话/登录进程，确认不会影响其他使用者。
- 仅适用于安装脚本得到的审计基线 0.7.0；哈希不一致立即停止，不用模糊替换。
- 原始 SHA256 `347235ccd693c74325fb37b49ec29a0b73128cc2d9c2cd42e55dd2ec18d93762`；补丁后 `51fac25726f5d15a78882780bc657cdac13831e1b847b324b85394342370829c`。

先检查（不修改）：

```sh
python3 /actual/skill/scripts/force_file_store.py \
  --package /actual/skill/scripts/.runtime/node_modules/@apify/mcpc
```

明确批准后才 `--apply`：

```sh
python3 /actual/skill/scripts/force_file_store.py \
  --package /actual/skill/scripts/.runtime/node_modules/@apify/mcpc --apply
```

原文件备份为同目录 `keychain.js.before-file-store`。不要在包管理器并发更新时执行；脚本不是完整事务/并发安全部署器。若需回滚，停止此副本使用者，核对备份和当前哈希，由管理员恢复；不要覆盖新版本。

## 持久性与保护

新授权写入所选 `MCPC_HOME_DIR/credentials.json`，明文 token 依赖目录 0700、文件 0600（Windows 用 ACL）。不把文件打印、交给模型、纳入 skill 包或版本库；不要自行复制 keyring token，按需要重新授权。

新 exec/SSH 下用相同入口/profile 做只读发现，才验证持久性。目录权限不等于加密，不抵抗 root。文件存储的刷新竞争、写入失败及回调 state 缺口仍见 [authentication.md](authentication.md)。
