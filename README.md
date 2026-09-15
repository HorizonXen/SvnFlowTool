# SvnFlow · 提交合并分支工具

> A focused SVN workflow for macOS and Windows — working copies, diffs, history, commits, and controlled Dev → Release merges in one place.
>
> 面向 macOS 与 Windows 的 SVN 工作流工具——集中完成工作副本管理、差异审查、历史查询、提交，以及受保护的 Dev → Release 定向合入。

[中文](#中文) · [English](#english)

## 中文

### 简介

SvnFlow 面向需要同时维护多个 SVN 工作副本、频繁审查配置差异并执行定向合入的团队。它调用用户电脑上已有的 Subversion 客户端，并沿用该客户端的认证配置；发行仓库不保存 SVN 密码、认证缓存、真实仓库地址、工作报告或用户配置。

主要能力：

- 管理多个 SVN 工作副本并查看递归文件状态
- 查看文本、Lua 和 Excel 差异
- 执行更新、提交、加入版本控制、撤销、清理、锁定与解锁
- 查询历史、浏览仓库，以及处理分支、标签和合并
- 按作者、提交和目录范围生成 Dev → Release 待合入内容
- 在真实写入前重新核验，并提供文件锁、备份和中断保护
- 简体中文与英文界面切换

### 安装

当前可安装版本：**1.26.0（构建 62）**。

系统要求：**macOS 14 或更高版本、Apple Silicon、已安装 `svn` 命令行客户端**。

直接安装最新版：

```sh
curl -fsSL https://raw.githubusercontent.com/HorizonXen/SvnFlowTool/main/install-macos.sh | /bin/sh
```

默认安装到 `~/Applications/提交合并分支工具.app`，不需要管理员权限。安装到其他目录：

```sh
curl -fsSL https://raw.githubusercontent.com/HorizonXen/SvnFlowTool/main/install-macos.sh | /bin/sh -s -- --install-dir /Applications
```

如果希望先检查脚本再运行：

```sh
git clone --depth 1 https://github.com/HorizonXen/SvnFlowTool.git
cd SvnFlowTool
/bin/sh ./install-macos.sh
```

安装器会校验平台、处理器架构、SHA-256、应用版本和代码签名。重复执行同一命令即可更新；若替换失败，会恢复原应用。

当前 macOS 包使用临时签名，适合本机验证。它尚未经过 Apple Developer ID 签名和公证，因此不是面向普通用户的正式公证发行版。安装器不会绕过 Gatekeeper。

Windows 10/11 x64 提供可安装的命令行版，复用与 macOS 应用相同的受保护合入和进度引擎。先下载并执行安装器：

```powershell
$installer = Join-Path $env:TEMP "install-svnflow.ps1"
Invoke-WebRequest https://raw.githubusercontent.com/HorizonXen/SvnFlowTool/main/install-windows.ps1 -OutFile $installer
powershell -NoProfile -ExecutionPolicy Bypass -File $installer -Repository HorizonXen/SvnFlowTool
```

重复执行同一组命令即可更新。安装后核对版本或查看合入命令：

```powershell
& "$env:LOCALAPPDATA\Programs\SvnFlow\SvnFlow.exe" --version
& "$env:LOCALAPPDATA\Programs\SvnFlow\SvnFlow.exe" merge --help
```

Windows 版要求系统已安装 `svn.exe` 且可从 `PATH` 调用。当前 Windows 包不包含 macOS 的 SwiftUI/AppKit 图形界面。

### 如何工作

1. 添加本地 SVN 工作副本；SvnFlow 读取本地状态和仓库信息。
2. 在提交或合入前查看目标文件、历史和差异。
3. 选择明确的作者、提交或目录范围进行核验。
4. 只有证据仍然有效时才写入本地工作副本；SVN 提交仍由用户明确发起。

### 隐私与安全

- 应用调用本机 `svn`，不收集或上传 SVN 凭据。
- 安装脚本不修改 shell 配置或系统 `PATH`。
- 安装包不包含真实 SVN 报告、仓库地址、开发机路径或用户配置。
- 发布内容可用 `/bin/sh ./scripts/check-public-release.sh` 复核。

## English

### Overview

SvnFlow provides a macOS desktop app and a Windows command-line tool for teams that work with multiple SVN working copies, review configuration changes, and perform selective Dev → Release integrations. It uses the Subversion client and authentication configuration already present on the user's machine. This distribution repository does not store SVN passwords, authentication caches, real repository URLs, work reports, or user configuration.

Key capabilities:

- Manage multiple SVN working copies and inspect recursive file status
- Review text, Lua, and Excel differences
- Update, commit, add, revert, clean up, lock, and unlock working-copy items
- Browse history and repositories, and work with branches, tags, and merges
- Build a Dev → Release integration scope by author, commit, and directory
- Revalidate before writes, with file locking, backups, and interruption protection
- Switch between Simplified Chinese and English

### Installation

Current installable release: **1.26.0 (build 62)**.

Requirements: **macOS 14 or later, Apple Silicon, and an installed `svn` command-line client**.

Install the latest release directly:

```sh
curl -fsSL https://raw.githubusercontent.com/HorizonXen/SvnFlowTool/main/install-macos.sh | /bin/sh
```

The default destination is `~/Applications/提交合并分支工具.app`; administrator privileges are not required. To choose another directory:

```sh
curl -fsSL https://raw.githubusercontent.com/HorizonXen/SvnFlowTool/main/install-macos.sh | /bin/sh -s -- --install-dir /Applications
```

To inspect the files before installation:

```sh
git clone --depth 1 https://github.com/HorizonXen/SvnFlowTool.git
cd SvnFlowTool
/bin/sh ./install-macos.sh
```

The installer verifies the platform, CPU architecture, SHA-256 checksum, app version, and code signature. Run the same command again to update. If replacement fails, the previous app is restored.

The current macOS package is ad-hoc signed for local evaluation. It is not yet an Apple Developer ID signed and notarized public release, and the installer does not bypass Gatekeeper.

Windows 10/11 x64 has an installable command-line release that uses the same guarded merge and progress engine as the macOS app. Download and run the installer:

```powershell
$installer = Join-Path $env:TEMP "install-svnflow.ps1"
Invoke-WebRequest https://raw.githubusercontent.com/HorizonXen/SvnFlowTool/main/install-windows.ps1 -OutFile $installer
powershell -NoProfile -ExecutionPolicy Bypass -File $installer -Repository HorizonXen/SvnFlowTool
```

Run the same commands again to update. Verify the installed version with:

```powershell
& "$env:LOCALAPPDATA\Programs\SvnFlow\SvnFlow.exe" --version
```

The Windows package requires `svn.exe` on `PATH`. It does not include the macOS SwiftUI/AppKit graphical interface.

### How it works

1. Add local SVN working copies; SvnFlow reads local status and repository metadata.
2. Review the target files, history, and differences before a commit or integration.
3. Select an explicit author, commit, or directory scope for verification.
4. Write to the local working copy only while the evidence remains valid; an SVN commit still requires an explicit user action.

### Privacy and security

- The app invokes the local `svn` client and does not collect or upload SVN credentials.
- The installer does not modify shell configuration or the system `PATH`.
- Release artifacts exclude real SVN reports, repository URLs, developer-machine paths, and user configuration.
- Run `/bin/sh ./scripts/check-public-release.sh` to verify the public distribution tree.

## Project status

The `main` branch contains installable release artifacts and installers. Reproducible build source and CI workflows are kept on the `source` branch. No open-source license has been granted for the distributed application.

Inspired by the clear, workflow-first documentation structure of [obra/superpowers](https://github.com/obra/superpowers).
