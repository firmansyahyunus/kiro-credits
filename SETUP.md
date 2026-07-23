# Setup

`kcredits` reads local Kiro CLI usage data for the current OS user. Reporting
has no runtime package dependency, no API key, and no network request.

## 1. Requirements

| Item | Required | Purpose |
|---|---:|---|
| Kiro CLI, signed in | Yes | Creates the local session data |
| Python 3.12+ | Yes | Runs `kcredits` |
| Same OS account | Yes | Keeps access within the current user's data |
| Git | Source clone only | Not needed after a package is installed |

Complete at least one Kiro response before expecting report data.

## 2. Install Kiro CLI

Use the current [official Kiro CLI installation guide](https://kiro.dev/docs/cli/installation/)
as the source of truth. Installer URLs and supported systems may change.

### Windows 11

Open PowerShell:

```powershell
irm 'https://cli.kiro.dev/install.ps1' | iex
kiro-cli --version
kiro-cli doctor
kiro-cli
```

### macOS

Open Terminal:

```bash
curl -fsSL https://cli.kiro.dev/install | bash
kiro-cli --version
kiro-cli doctor
kiro-cli
```

### Ubuntu or another supported Linux distribution

The official guide currently provides AppImage, ZIP, and Ubuntu `.deb` options.
For Ubuntu:

```bash
wget https://desktop-release.q.us-east-1.amazonaws.com/latest/kiro-cli.deb
sudo dpkg -i kiro-cli.deb
sudo apt-get install -f
kiro-cli --version
kiro-cli doctor
kiro-cli
```

Review the official guide for architecture and `glibc` requirements before
using the ZIP or AppImage variants.

## 3. Install Python

Python 3.12 is the currently validated local baseline.

### Windows

```powershell
winget install --exact --id Python.Python.3.12
py -3.12 --version
```

Alternatively, use the signed installer from
[python.org](https://www.python.org/downloads/windows/).

### macOS

Use the universal installer from
[python.org](https://www.python.org/downloads/macos/) or, if Homebrew is already
trusted on the machine:

```bash
brew install python@3.12
python3.12 --version
```

### Ubuntu

Use packages supplied by the supported Ubuntu release:

```bash
sudo apt update
sudo apt install -y python3 python3-venv git
python3 --version
```

Do not replace the distribution's system Python manually. If Python 3.12 is not
available, use a supported environment or a user-managed Python installation.

## 4. Run from source

### Windows

```powershell
git clone https://github.com/firmansyahyunus/kiro-credits.git
Set-Location .\kiro-credits
py -3.12 .\kcredits.py doctor
py -3.12 .\kcredits.py report today
```

### macOS or Linux

```bash
git clone https://github.com/firmansyahyunus/kiro-credits.git
cd kiro-credits
python3 ./kcredits.py doctor
python3 ./kcredits.py report today
```

## 5. Install the local package

From a reviewed source checkout:

```powershell
# Windows
py -3.12 -m pip install .
kcredits doctor
```

```bash
# macOS / Linux
python3 -m pip install .
kcredits doctor
```

This package contains no third-party runtime dependency. Do not publish it to
PyPI until the public release checklist is complete.

## 6. Troubleshooting

### `No credit data found`

1. Confirm Kiro CLI is signed in.
2. Complete one Kiro response.
3. Run `kcredits doctor`.
4. Confirm `kcredits` and Kiro are running as the same OS user.

### `kcredits` command not found

Run directly from source, or ensure Python's user scripts directory is on
`PATH`. A tool manager such as `pipx` can isolate the command after the package
is publicly released.

### Archive location

`snapshot`, `snapshot-all`, and `migrate-archive` write under
`~/.kcredits/` by default. The archive contains project paths and usage
metadata. Keep it private and outside repositories.
