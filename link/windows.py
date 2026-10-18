"""Download and elevate the Windows pieces the Linux installer gets from the package manager."""

from __future__ import annotations

import os
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .common import is_windows

WIREGUARD_INDEX = "https://download.wireguard.com/windows-client/"
USER_AGENT = "civrev-link"
CANCELLED = 1223


def wireguard_arch(machine: str) -> str:
    normalized = machine.lower()
    if normalized in {"amd64", "x86_64"}:
        return "amd64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    if normalized in {"x86", "i386", "i686"}:
        return "x86"
    raise SystemExit(f"No WireGuard installer for this processor ({machine}).")


def latest_msi_name(page: str, arch: str) -> str:
    versions = re.findall(rf"wireguard-{re.escape(arch)}-(\d+(?:\.\d+)*)\.msi", page, flags=re.IGNORECASE)
    if not versions:
        raise SystemExit(f"The official WireGuard download page has no {arch} installer.")
    latest = max(versions, key=lambda item: tuple(int(part) for part in item.split(".")))
    return f"wireguard-{arch}-{latest}.msi"


def msiexec_install_args(msi: Path) -> list[str]:
    return ["msiexec", "/i", str(msi), "/qn", "DO_NOT_LAUNCH=1"]


def admin_batch(commands: list[list[str]], *, required: int) -> str:
    """A cmd script. The first `required` commands must succeed; the rest are best effort."""
    lines = ["@echo off"]
    for index, command in enumerate(commands):
        lines.append(subprocess.list2cmdline(command))
        if index < required:
            lines.append("if errorlevel 1 exit /b %errorlevel%")
    lines.append("exit /b 0")
    return "\r\n".join(lines) + "\r\n"


def is_admin() -> bool:
    if not is_windows():
        return False
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def install_wireguard(dest_dir: Path) -> None:
    import platform

    print("Installing WireGuard. Windows will ask for administrator approval.", flush=True)
    arch = wireguard_arch(platform.machine())
    page = _fetch(WIREGUARD_INDEX)
    name = latest_msi_name(page, arch)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / name
    if not target.exists():
        print(f"downloading {name}", flush=True)
        _download(WIREGUARD_INDEX + name, target)
    run_as_admin(msiexec_install_args(target), accept=(0, 3010))


def run_as_admin(argv: list[str], *, accept: tuple[int, ...] = (0,)) -> None:
    _run_admin_batch(admin_batch([argv], required=1), accept=accept)


def run_admin_batch(commands: list[list[str]], *, required: int) -> None:
    _run_admin_batch(admin_batch(commands, required=required), accept=(0,))


def tunnel_service_name(conf: Path) -> str:
    """WireGuard names the Windows service after the config file."""
    return f"WireGuardTunnel${conf.stem}"


def tunnel_action(state: str | None) -> str:
    """A running tunnel is left alone. A stopped one is started. A missing one is installed."""
    if state == "running":
        return "skip"
    if state is None:
        return "install"
    return "start"


def tunnel_state(conf: Path) -> str | None:
    result = subprocess.run(
        ["sc", "query", tunnel_service_name(conf)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    match = re.search(r"STATE\s*:\s*(\d+)", result.stdout)
    if match is None:
        return None
    if int(match.group(1)) == 4:
        return "running"
    return "stopped"


def _run_admin_batch(script: str, *, accept: tuple[int, ...]) -> None:
    if not is_windows():
        raise SystemExit("This step only runs on Windows.")
    if is_admin():
        _run_batch_here(script, accept)
        return
    path = _write_batch(script)
    try:
        code = _start_elevated(path)
    finally:
        path.unlink(missing_ok=True)
    if code == CANCELLED:
        raise SystemExit("The administrator prompt was declined. Run the installer again and approve it.")
    if code not in accept:
        raise SystemExit(f"Administrator step failed (exit {code}).")


def _run_batch_here(script: str, accept: tuple[int, ...]) -> None:
    path = _write_batch(script)
    try:
        result = subprocess.run(["cmd", "/d", "/c", str(path)], check=False)
    finally:
        path.unlink(missing_ok=True)
    if result.returncode not in accept:
        raise SystemExit(f"Administrator step failed (exit {result.returncode}).")


def _write_batch(script: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".cmd", delete=False, encoding="utf-8", newline="")
    handle.write(script)
    handle.close()
    return Path(handle.name)


def _start_elevated(script: Path) -> int:
    quoted = "'" + str(script).replace("'", "''") + "'"
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "try { "
        f"$p = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d','/c',{quoted}) -Verb RunAs -Wait -PassThru "
        "} catch { exit 1223 }; "
        "if ($null -eq $p) { exit 1223 }; "
        "exit $p.ExitCode"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=False,
    )
    return completed.returncode


def _fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60, context=ssl.create_default_context()) as response:
        return response.read().decode("utf-8", errors="replace")


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    temporary = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(request, timeout=120, context=ssl.create_default_context()) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    os.replace(temporary, dest)
