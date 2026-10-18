"""Choose an official Python build. The shell bootstrap installs it before this package can run."""

from __future__ import annotations

import re

MINIMUM = (3, 11)


def windows_installer_url(page: str, machine: str) -> str:
    """The newest published installer. Release headings include alphas that have no stable .exe yet."""
    suffix = _installer_suffix(machine)
    if suffix:
        pattern = rf"https://www\.python\.org/ftp/python/(\d+\.\d+\.\d+)/python-\1-{suffix}\.exe"
    else:
        pattern = r"https://www\.python\.org/ftp/python/(\d+\.\d+\.\d+)/python-\1\.exe"
    found: list[tuple[tuple[int, ...], str]] = []
    for match in re.finditer(pattern, page):
        version = tuple(int(part) for part in match.group(1).split("."))
        if version >= MINIMUM:
            found.append((version, match.group(0)))
    if not found:
        raise SystemExit("Could not find a Python 3.11 or newer Windows installer.")
    return max(found)[1]


def _installer_suffix(machine: str) -> str:
    normalized = machine.lower()
    if normalized in {"x86", "i386", "i686"}:
        return ""
    suffix = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(normalized)
    if suffix is None:
        raise SystemExit(f"No Python installer for this processor ({machine}).")
    return suffix
