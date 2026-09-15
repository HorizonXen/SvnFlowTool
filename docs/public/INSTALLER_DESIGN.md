# Installer design basis

The release layout follows established patterns from widely used GitHub projects:

- [uv installation](https://github.com/astral-sh/uv/blob/main/docs/getting-started/installation.md): separate shell and PowerShell installers, versioned standalone artifacts, custom install directories and scripts that can be inspected before execution.
- [uv installer reference](https://github.com/astral-sh/uv/blob/main/docs/reference/installer.md): environment-variable overrides and an explicit way to avoid modifying shell configuration.
- [rustup installer](https://github.com/rust-lang/rustup/blob/main/rustup-init.sh): early platform/architecture detection, strict shell behavior, prerequisites checked before mutation and temporary download directories.
- [ripgrep releases](https://github.com/BurntSushi/ripgrep/releases): clearly named prebuilt archives for each operating system and architecture.

SvnFlow adapts those conventions for a GUI application: user-level installation by default, SHA-256 and embedded-version validation, atomic replacement with rollback, no implicit PATH edits, and no silent privilege escalation. macOS and Windows assets are never substituted for one another, and an engine-only validation artifact is not accepted as a Windows desktop package.
