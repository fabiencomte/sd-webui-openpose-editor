"""Safe distribution updater used by the Forge OpenPose editor wrapper."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import threading
from typing import Any
from urllib.parse import quote
import zipfile

import requests


REQUEST_TIMEOUT = (5, 30)
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_EXTRACTED_BYTES = 75 * 1024 * 1024
RELEASE_ASSET_NAME = "dist.zip"
_UPDATE_LOCK = threading.Lock()
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class UpdateError(RuntimeError):
    """Raised when a release cannot be downloaded or installed safely."""


def normalize_version(version: str) -> str:
    value = version.strip()
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"Unsupported version: {version!r}")
    return "v" + ".".join(match.groups())


def version_tuple(version: str) -> tuple[int, int, int]:
    normalized = normalize_version(version)
    return tuple(int(part) for part in normalized[1:].split("."))  # type: ignore[return-value]


def need_update(current_version: str | None, package_version: str) -> bool:
    if current_version is None:
        return True
    return version_tuple(current_version) != version_tuple(package_version)


def read_version_file(dist_dir: Path) -> str | None:
    version_path = dist_dir / "version.txt"
    if not version_path.is_file():
        return None
    try:
        return normalize_version(version_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_package_version(extension_dir: Path) -> str:
    try:
        data = json.loads((extension_dir / "package.json").read_text(encoding="utf-8"))
        version = data["version"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise UpdateError("package.json does not contain a valid version") from exc
    if not isinstance(version, str):
        raise UpdateError("package.json version must be a string")
    try:
        return normalize_version(version)
    except ValueError as exc:
        raise UpdateError(str(exc)) from exc


def _checked_response(response: requests.Response, context: str) -> requests.Response:
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise UpdateError(f"{context} failed: {exc}") from exc
    return response


def get_release_asset_url(
    owner: str,
    repo: str,
    version: str,
    *,
    session: Any = requests,
) -> str:
    tag = normalize_version(version)
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{quote(tag)}"
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise UpdateError(f"GitHub release request failed: {exc}") from exc
    _checked_response(response, "GitHub release request")
    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise UpdateError("GitHub release response is not valid JSON") from exc

    assets = data.get("assets") if isinstance(data, dict) else None
    if not isinstance(assets, list):
        raise UpdateError(f"Release {tag} has no assets")
    matching = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == RELEASE_ASSET_NAME]
    if len(matching) != 1:
        raise UpdateError(f"Release {tag} must contain exactly one {RELEASE_ASSET_NAME} asset")
    asset_url = matching[0].get("browser_download_url")
    if not isinstance(asset_url, str) or not asset_url.startswith("https://github.com/"):
        raise UpdateError(f"Release {tag} has an invalid asset URL")
    return asset_url


def download_archive(url: str, destination: Path, *, session: Any = requests) -> None:
    try:
        response = session.get(url, stream=True, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        raise UpdateError(f"Release download failed: {exc}") from exc
    _checked_response(response, "Release download")

    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_ARCHIVE_BYTES:
                raise UpdateError("Release archive is larger than the safety limit")
        except ValueError as exc:
            raise UpdateError("Release response has an invalid Content-Length") from exc

    written = 0
    try:
        with destination.open("xb") as archive:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                written += len(chunk)
                if written > MAX_ARCHIVE_BYTES:
                    raise UpdateError("Release archive exceeded the safety limit while downloading")
                archive.write(chunk)
    except OSError as exc:
        raise UpdateError(f"Cannot write release archive: {exc}") from exc


def _safe_member_path(info: zipfile.ZipInfo) -> PurePosixPath:
    normalized = info.filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise UpdateError(f"Unsafe archive path: {info.filename!r}")
    if path.parts and re.fullmatch(r"[A-Za-z]:", path.parts[0]):
        raise UpdateError(f"Unsafe archive path: {info.filename!r}")
    mode = info.external_attr >> 16
    if mode & 0o170000 == 0o120000:
        raise UpdateError(f"Archive symlinks are not allowed: {info.filename!r}")
    return path


def safe_extract_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            total_size = sum(info.file_size for info in infos)
            if total_size > MAX_EXTRACTED_BYTES:
                raise UpdateError("Extracted release is larger than the safety limit")
            for info in infos:
                member = _safe_member_path(info)
                target = destination.joinpath(*member.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=64 * 1024)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"Invalid release archive: {exc}") from exc


def validate_distribution(candidate: Path, expected_version: str) -> None:
    if not (candidate / "index.html").is_file():
        raise UpdateError("Release archive does not contain index.html")
    actual_version = read_version_file(candidate)
    if actual_version != normalize_version(expected_version):
        raise UpdateError(
            f"Release version mismatch: expected {normalize_version(expected_version)}, got {actual_version!r}"
        )


def atomic_replace_directory(candidate: Path, destination: Path) -> None:
    backup = destination.with_name(f".{destination.name}.backup-{os.getpid()}-{threading.get_ident()}")
    if backup.exists():
        raise UpdateError(f"Temporary backup already exists: {backup}")
    moved_old = False
    try:
        if destination.exists():
            destination.replace(backup)
            moved_old = True
        candidate.replace(destination)
    except OSError as exc:
        if moved_old and backup.exists() and not destination.exists():
            backup.replace(destination)
        raise UpdateError(f"Cannot activate the downloaded editor: {exc}") from exc
    else:
        if backup.exists():
            shutil.rmtree(backup)


def install_release(
    extension_dir: Path,
    owner: str,
    repo: str,
    version: str,
    *,
    session: Any = requests,
) -> None:
    extension_dir = extension_dir.resolve()
    dist_dir = extension_dir / "dist"
    with _UPDATE_LOCK:
        with tempfile.TemporaryDirectory(prefix=".openpose-update-", dir=extension_dir) as temp_name:
            temp_dir = Path(temp_name)
            archive_path = temp_dir / RELEASE_ASSET_NAME
            candidate = temp_dir / "candidate"
            asset_url = get_release_asset_url(owner, repo, version, session=session)
            download_archive(asset_url, archive_path, session=session)
            safe_extract_archive(archive_path, candidate)
            validate_distribution(candidate, version)
            atomic_replace_directory(candidate, dist_dir)
