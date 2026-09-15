# SvnFlow · 提交合并分支工具

SvnFlow 是一个面向多工作副本流程的 SVN 桌面工具。它把工作副本导航、文件状态、差异、历史、提交和可配置的定向合入放在同一个工作区中。

## 平台状态

| 平台 | 当前状态 | 发行形式 |
| --- | --- | --- |
| macOS 14+（Apple Silicon） | 原生 SwiftUI/AppKit 应用可构建 | `.app` / ZIP；正式公开发行前需 Developer ID 签名与公证 |
| Windows 10/11 x64 | 可安装的命令行版，共享合入引擎、配置与文件锁 | `SvnFlow.exe` / ZIP；GitHub 标签发布时与 macOS 包同步生成 |

Windows 不是把现有 AppKit 界面重新编译一次即可完成。项目采用“共享业务引擎 + 平台入口”的迁移方式；当前 Windows 入口是 PowerShell/命令行，操作对象、选择范围、安全保护和结果语义与 macOS 应用共用同一套引擎。

## 主要能力

- 管理多个 SVN 工作副本并查看递归文件状态
- 文本、Lua 与 Excel 差异查看
- 更新、提交、加入版本控制、撤销、清理、锁定与解锁
- 历史、仓库浏览、分支/标签和合并
- 按作者与范围生成源分支到目标分支的待合入副本
- 手动设置源目录和目标目录，并以路径末级目录名动态显示合入方向
- 对真实写入使用重新核验、文件锁、备份与中断保护

所有 SVN 操作调用用户机器上的 Subversion 客户端，并沿用该客户端的认证配置。仓库不会保存 SVN 密码或认证缓存。

## 本地验证

```sh
swift run SVNCoreChecks
python3 -m unittest discover -s Tests/CrossPlatform -v
python3 scripts/check_public_tree.py
```

macOS 构建：

```sh
python3 -m pip install -r packaging/engine-requirements.txt
python3 packaging/build_engine.py
zsh scripts/build-app.sh
```

Windows 10/11 x64 构建（PowerShell）：

```powershell
python -m pip install -r packaging/engine-requirements.txt
.\packaging\build-windows.ps1
```

安装、更新和版本核对：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\install-windows.ps1
& "$env:LOCALAPPDATA\Programs\SvnFlow\SvnFlow.exe" --version
```

Windows 产物为 `dist\SvnFlow-Windows-x64-<version>-<build>.zip`。推送 `v*` 标签时，GitHub Actions 会同时构建 macOS 和 Windows 包，并上传两个平台的 ZIP、SHA-256、安装脚本及 `release.json` 到同一个 GitHub Release。

版本以 `release.json` 为准。当前版本为 **1.26.0（构建 62）**。配置本机 `.svnflow-delivery-path` 后，发行仍分为三个明确步骤：

```sh
packaging/build-release.sh
# 人工试用当前精确安装包并确认通过后：
packaging/approve-trial.sh
packaging/publish-approved-release.sh
```

构建只生成试用包，不会刷新最终交付目录。确认绑定版本、构建号与 SHA-256；包被重建或版本变化后必须重新试用确认。

## 公开发布安全

真实报告、日志、工作簿、开发机配置、构建物、归档、内置运行环境和内部 Penpot 元数据默认不进入 Git。发布前请阅读 [公开发布清单](docs/public/PUBLIC_RELEASE.md) 与 [安全策略](docs/public/SECURITY.md)。

目前尚未选择开源许可证。版权持有人确认许可证及所引用/改编代码的来源许可之前，请勿把源码标注为“开源”。
