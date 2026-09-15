# SvnFlow 安装包

本目录只存放最终交付文件，不包含开发日志、真实 SVN 报告或用户配置。

此目录只能由已通过人工试用、且版本、构建号和 SHA-256 均匹配的安装包更新。仓库中的试用构建不会自动下发到这里。

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

## Windows 10/11 · x64 命令行版

在 PowerShell 中进入本目录后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-windows.ps1
```

默认安装到当前用户的 `%LOCALAPPDATA%\Programs\SvnFlow`，不需要管理员权限，并创建开始菜单快捷方式。

从 GitHub Release 直接安装或更新时，可下载 `install-windows.ps1` 后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-windows.ps1 -Repository OWNER/REPOSITORY
```

安装完成后可在 PowerShell 中核对版本，并调用共享合入引擎：

```powershell
& "$env:LOCALAPPDATA\Programs\SvnFlow\SvnFlow.exe" --version
& "$env:LOCALAPPDATA\Programs\SvnFlow\SvnFlow.exe" merge --help
```

Windows 版当前提供可安装的命令行工具，使用与 macOS 应用相同的合入业务引擎和保护规则；macOS 的 SwiftUI/AppKit 图形界面不包含在 Windows 包中。

## 安全约定

- 安装前校验 SHA-256、平台、架构和包内版本。
- 更新采用临时目录和失败回滚，不直接覆盖正在验证的旧版本。
- 安装脚本不会写入 SVN 凭据，不会修改 shell 配置或系统 PATH。
- 可先用文本编辑器检查安装脚本，再执行命令。
