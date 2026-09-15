"""Create an isolated, real local SVN workspace for reviewing the interface."""
from pathlib import Path
import shutil
import subprocess

workspace = Path(__file__).resolve().parent.parent
base = workspace / ".build" / "ui-preview"
if (base / "ready").exists():
    print(base)
    raise SystemExit(0)
if base.exists():
    raise SystemExit(f"Incomplete preview exists: {base}; inspect it before rebuilding.")
svn = shutil.which("svn")
admin = shutil.which("svnadmin")
if not svn or not admin:
    raise SystemExit("Subversion and svnadmin are required.")
base.mkdir(parents=True)
repository = base / "repository"
subprocess.run([admin, "create", str(repository)], check=True)

def command(*args):
    return subprocess.run([svn, "--non-interactive", *map(str, args)], check=True, capture_output=True, text=True)

url = repository.as_uri()
command("mkdir", url + "/trunk", url + "/branches", "-m", "Create project layout", "--username", "alex")
dev = base / "Dev_Develop"
command("checkout", url + "/trunk", dev)
files = {
    "Assets/Scripts/Game/GameClient.cs": '''using System;
using System.Threading.Tasks;

namespace Client.Game
{
    public sealed class GameClient
    {
        private const int RetryCount = 3;
        private const int TimeoutSeconds = 10;

        public async Task ConnectAsync()
        {
            await ConnectToServerAsync(TimeoutSeconds);
            Console.WriteLine("Connected to server");
        }

        private Task ConnectToServerAsync(int timeout)
        {
            return Task.CompletedTask;
        }
    }
}
''',
    "Assets/Scripts/Game/PlayerController.cs": "namespace Client.Game { public sealed class PlayerController { } }\n",
    "Assets/Scripts/Game/WorldManager.cs": "namespace Client.Game { public sealed class WorldManager { } }\n",
    "Assets/Scripts/Network/Connection.cs": "namespace Client.Network { public sealed class Connection { } }\n",
    "Assets/Scripts/Network/PacketReader.cs": "namespace Client.Network { public sealed class PacketReader { } }\n",
    "Assets/Scripts/Network/RequestQueue.cs": "namespace Client.Network { public sealed class RequestQueue { } }\n",
    "Assets/Scripts/UI/LoginView.cs": "namespace Client.UI { public sealed class LoginView { } }\n",
    "Assets/Scripts/UI/MainMenuView.cs": "namespace Client.UI { public sealed class MainMenuView { } }\n",
    "Assets/Scripts/UI/SettingsView.cs": "namespace Client.UI { public sealed class SettingsView { } }\n",
    "Assets/Resources/Config/client.json": '{"environment": "development", "timeout": 10}\n',
    "Assets/Resources/Config/graphics.json": '{"quality": "high"}\n',
    "Assets/Resources/Localization/en.json": '{"welcome": "Welcome back"}\n',
    "Assets/Resources/Localization/zh.json": '{"welcome": "欢迎回来"}\n',
    "CommonRes/Shared/constants.json": '{"version": "1.2.0"}\n',
    "Docs/architecture.md": "# Client architecture\n\nGame, networking, resources, and presentation.\n",
    "Docs/changelog.md": "# Changelog\n\n## 1.2.0\nImprove startup performance.\n",
    "HybridCLRData/README.md": "# Runtime data\n",
    "Launcher/launcher.json": '{"channel": "development"}\n',
    "LuaTemplates/module.lua": "local module = {}\nreturn module\n",
    "Packages/manifest.json": '{"dependencies": {}}\n',
    "ProjectSettings/ProjectVersion.txt": "m_EditorVersion: 2022.3\n",
    "ProjectSettings/QualitySettings.asset": "QualitySettings:\n  currentQuality: 2\n",
    "Protocol/session.proto": 'syntax = "proto3";\nmessage Session { string id = 1; }\n',
    "Ref/README.md": "# References\n",
    "Tools/build.sh": "#!/bin/sh\necho 'Build client'\n",
    "Wwise/audio.json": '{"volume": 1.0}\n',
    ".github/workflows/build.yml": "name: Client Build\n",
    ".gitignore": "Library/\nTemp/\n",
    "README.md": "# Client\n\nLocal interface review workspace.\n",
}
for name, content in files.items():
    path = dev / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
command("add", "--force", dev)
command("commit", dev, "-m", "Add client project and resource structure", "--username", "alex")
changes = [
    ("Docs/changelog.md", "\nDocument connection retry behavior.\n", "Document network retry behavior", "mia"),
    ("Tools/build.sh", "echo 'Validate resource manifest'\n", "Validate resources before packaging", "chen"),
    ("Assets/Scripts/UI/SettingsView.cs", "// Keep user preferences between sessions.\n", "Persist client display preferences", "alex"),
    ("Docs/architecture.md", "\nRequests are processed by the network queue.\n", "Clarify request queue ownership", "mia"),
]
for name, content, message, author in changes:
    path = dev / name
    with path.open("a") as stream:
        stream.write(content)
    command("commit", path, "-m", message, "--username", author)
command("copy", url + "/trunk", url + "/branches/release-1.2", "-m", "Create release 1.2 branch", "--username", "alex")
command("copy", url + "/branches/release-1.2", url + "/branches/hotfix-1.2.1", "-m", "Prepare hotfix 1.2.1", "--username", "chen")
command("checkout", url + "/branches/release-1.2", base / "Release_1.2")
command("checkout", url + "/branches/hotfix-1.2.1", base / "HotFix_1.2.1")
command("update", dev)
path = dev / "Assets/Scripts/Game/GameClient.cs"
path.write_text(path.read_text().replace("RetryCount = 3", "RetryCount = 5").replace("TimeoutSeconds = 10", "TimeoutSeconds = 30"))
(dev / "Assets/Resources/Config/client.json").write_text('{"environment": "development", "timeout": 30}\n')
command("propset", "svn:eol-style", "LF", dev / "Assets/Scripts/Network/Connection.cs")
command("delete", dev / "LuaTemplates/module.lua")
(dev / "Assets/Scripts/Network/RetryPolicy.cs").write_text("namespace Client.Network { public sealed class RetryPolicy { } }\n")
command("add", dev / "Assets/Scripts/Network/RetryPolicy.cs")
(dev / "Docs/release-notes.md").write_text("# Release notes\n\nDraft.\n")
(base / "ready").write_text("Generated local-only SVN UI fixture.\n")
print(base)
