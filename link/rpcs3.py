"""Download official RPCS3 and write the shared Civilization Revolution config."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from .common import HOST_IP, LINUX_RELEASE_API, TITLE_IDS, WINDOWS_RELEASE_API, is_windows, rpcs3_config_dirs

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


def download_linked_file(url: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = filename_from_url(url)
    target = dest_dir / name
    marker = dest_dir / f"{name}.source"
    if target.exists() and marker.exists() and marker.read_text(encoding="utf-8") == url:
        return target
    print(f"downloading {name}", flush=True)
    _download(url, target)
    marker.write_text(url, encoding="utf-8")
    return target


def filename_from_url(url: str) -> str:
    name = Path(urllib.parse.urlparse(url).path).name
    if not name or name in {".", ".."}:
        raise SystemExit("the link does not include a file name")
    return name


def install_firmware(binary: Path, pup: Path) -> None:
    if pup.suffix.lower() != ".pup":
        raise SystemExit(f"{pup} is not a PS3 firmware .pup file")
    try:
        subprocess.check_call([str(binary), "--installfw", str(pup)])
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"RPCS3 could not install the firmware (exit {exc.returncode}). "
            "Run ./install.sh as your desktop user so it can open a window."
        ) from None


def write_game_config(install_dir: Path, overlay_ip: str) -> list[Path]:
    return _write_configs(rpcs3_config_dirs(install_dir), overlay_ip)


def _write_configs(roots: list[Path], overlay_ip: str) -> list[Path]:
    written: list[Path] = []
    body = _game_yaml(overlay_ip)
    pad = _keyboard_yaml()
    for root in roots:
        folder = root / "config" / "custom_configs"
        folder.mkdir(parents=True, exist_ok=True)
        for title_id in TITLE_IDS:
            path = folder / f"config_{title_id}.yml"
            path.write_text(body, encoding="utf-8")
            written.append(path)
            pad_dir = root / "config" / "input_configs" / title_id
            pad_dir.mkdir(parents=True, exist_ok=True)
            pad_path = pad_dir / "Default.yml"
            pad_path.write_text(pad, encoding="utf-8")
            written.append(pad_path)
    return written


def _game_yaml(overlay_ip: str) -> str:
    return (
        "Net:\n"
        "  Internet enabled: Connected\n"
        f"  IP address: {overlay_ip}\n"
        f"  Bind address: {overlay_ip}\n"
        f"  DNS address: {HOST_IP}\n"
        "  UPNP Enabled: false\n"
        "  PSN status: Disconnected\n"
        "Miscellaneous:\n"
        "  Silence All Logs: true\n"
        "Input/Output:\n"
        '  Mouse: "Null"\n'
    )


def _keyboard_yaml() -> str:
    """Keyboard pad RPCS3 loads for this title. Mouse movement is the left stick."""
    return (
        "Player 1 Input:\n"
        "  Handler: Keyboard\n"
        "  Device: Keyboard\n"
        "  Config:\n"
        "    Left Stick Left: Mouse MLeft\n"
        "    Left Stick Down: Mouse MDown\n"
        "    Left Stick Right: Mouse MRight\n"
        "    Left Stick Up: Mouse MUp\n"
        "    Right Stick Left: A\n"
        "    Right Stick Down: S\n"
        "    Right Stick Right: D\n"
        "    Right Stick Up: W\n"
        "    Start: Return,Enter\n"
        "    Select: Tab\n"
        "    Square: Space\n"
        "    Cross: Mouse Left\n"
        "    Circle: Mouse Right,Esc\n"
        "    Triangle: Mouse Middle,V\n"
        "    Left: Left\n"
        "    Down: Down\n"
        "    Right: Right\n"
        "    Up: Up\n"
        "    R1: E\n"
        "    R2: C\n"
        "    L1: Q\n"
        "    L2: Z,Wheel Up,Wheel Down\n"
        "    Mouse Movement Mode: Relative\n"
        "    Mouse Deadzone X Axis: 5\n"
        "    Mouse Deadzone Y Axis: 5\n"
        "    Mouse Acceleration X Axis: 600\n"
        "    Mouse Acceleration Y Axis: 600\n"
        "    Left Stick Lerp Factor: 100\n"
        "    Right Stick Lerp Factor: 100\n"
        '  Buddy Device: ""\n'
    )


def control_summary() -> str:
    return (
        "Mouse and keyboard: move the mouse to pick a tile, left click to confirm, "
        "right click or Esc to cancel. WASD pans the map. Arrow keys cycle units. "
        "Q city, E diplomacy, Z or the wheel zooms, C info, Space skips, "
        "middle click or V is the special action, Enter pauses, Tab opens options."
    )


SEVEN_ZIP_URL = "https://www.7-zip.org/a/7zr.exe"


def _extract_windows(archive: Path, dest_dir: Path) -> Path:
    extractor = _windows_extractor(dest_dir)
    subprocess.check_call([str(extractor), "x", "-y", f"-o{dest_dir}", str(archive)])
    found = next(dest_dir.rglob("rpcs3.exe"), None)
    if found is None:
        raise SystemExit("RPCS3 archive unpacked, but rpcs3.exe was not in it")
    return found


def _windows_extractor(dest_dir: Path) -> Path:
    found = shutil.which("7z") or shutil.which("7za")
    if found:
        return Path(found)
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    installed = Path(program_files) / "7-Zip" / "7z.exe"
    if installed.is_file():
        return installed
    bundled = dest_dir / "7zr.exe"
    if not bundled.exists():
        print("downloading the 7-Zip extractor", flush=True)
        _download(SEVEN_ZIP_URL, bundled)
    return bundled


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
