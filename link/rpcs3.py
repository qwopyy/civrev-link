"""Download official RPCS3 and write the shared Civilization Revolution config."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import subprocess
import urllib.request
from pathlib import Path

from .common import LINUX_RELEASE_API, TITLE_IDS, WINDOWS_RELEASE_API, is_windows, rpcs3_config_dirs

USER_AGENT = "civrev-link"


def download_rpcs3(dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    api = WINDOWS_RELEASE_API if is_windows() else LINUX_RELEASE_API
    release = _get_json(api)
    suffix = "_win64_msvc.7z" if is_windows() else "_linux64.AppImage"
    asset = next(item for item in release["assets"] if item["name"].endswith(suffix))
    target = dest_dir / asset["name"]
    if not target.exists():
        print(f"downloading {asset['name']} from the official RPCS3 release", flush=True)
        _download(asset["browser_download_url"], target)
        _check_digest(target, asset.get("digest", ""), release.get("body", ""))
    if is_windows():
        return _extract_windows(target, dest_dir)
    target.chmod(0o755)
    return target


def install_firmware(binary: Path, pup: Path) -> None:
    if pup.suffix.lower() != ".pup":
        raise SystemExit(f"{pup} is not a PS3 firmware .pup file")
    subprocess.check_call([str(binary), "--installfw", str(pup)])


def write_game_config(install_dir: Path, overlay_ip: str) -> list[Path]:
    written: list[Path] = []
    body = _game_yaml(overlay_ip)
    for root in rpcs3_config_dirs(install_dir):
        folder = root / "config" / "custom_configs"
        folder.mkdir(parents=True, exist_ok=True)
        for title_id in TITLE_IDS:
            path = folder / f"config_{title_id}.yml"
            path.write_text(body, encoding="utf-8")
            written.append(path)
    return written


def _game_yaml(overlay_ip: str) -> str:
    return (
        "Net:\n"
        "  Internet enabled: Connected\n"
        f"  IP address: {overlay_ip}\n"
        f"  Bind address: {overlay_ip}\n"
        "  DNS address: 8.8.8.8\n"
        "  UPNP Enabled: false\n"
        "  PSN status: Disconnected\n"
        "Miscellaneous:\n"
        "  Silence All Logs: true\n"
    )


def _extract_windows(archive: Path, dest_dir: Path) -> Path:
    extractor = shutil.which("7z") or shutil.which("7za")
    if extractor is None:
        raise SystemExit("Install 7-Zip so the Windows RPCS3 archive can be unpacked, then run the installer again.")
    subprocess.check_call([extractor, "x", "-y", f"-o{dest_dir}", str(archive)])
    found = next(dest_dir.rglob("rpcs3.exe"), None)
    if found is None:
        raise SystemExit("RPCS3 archive unpacked, but rpcs3.exe was not in it")
    return found


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60, context=ssl.create_default_context()) as response:
        return json.load(response)


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    temporary = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(request, timeout=120, context=ssl.create_default_context()) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    os.replace(temporary, dest)


def _check_digest(path: Path, digest_field: str, body: str) -> None:
    expected = ""
    if digest_field.startswith("sha256:"):
        expected = digest_field.split(":", 1)[1]
    elif len(body) >= 64 and all(c in "0123456789abcdef" for c in body[:64].lower()):
        expected = body[:64].lower()
    if not expected:
        return
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        path.unlink(missing_ok=True)
        raise SystemExit(f"RPCS3 download checksum did not match the official release ({path.name})")
