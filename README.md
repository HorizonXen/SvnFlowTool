# SvnFlow 安装包

本目录只存放最终交付文件，不包含开发日志、真实 SVN 报告或用户配置。

## macOS 14+ · Apple Silicon

在终端进入本目录后执行：

```sh
/bin/sh ./install-macos.sh
```

默认安装到 `~/Applications/提交合并分支工具.app`，不需要管理员权限。指定其他目录：

```sh
/bin/sh ./install-macos.sh --install-dir /Applications
```

当前包使用临时签名，适合本机验证；面向公众发布前仍需 Developer ID 签名和公证。

## Windows 10/11 · x64

在 PowerShell 中进入本目录后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-windows.ps1
```

默认安装到当前用户的 `%LOCALAPPDATA%\Programs\SvnFlow`，不需要管理员权限，并创建开始菜单快捷方式。

Windows GUI 包尚未完成时，安装器会明确停止，不会把内部验证引擎伪装成桌面应用。

## 安全约定

- 安装前校验 SHA-256、平台、架构和包内版本。
- 更新采用临时目录和失败回滚，不直接覆盖正在验证的旧版本。
- 安装脚本不会写入 SVN 凭据，不会修改 shell 配置或系统 PATH。
- 可先用文本编辑器检查安装脚本，再执行命令。
