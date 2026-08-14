from __future__ import annotations

from pathlib import Path
import zipfile

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from openpose_editor_backend import (
    REQUEST_TIMEOUT,
    UpdateError,
    atomic_replace_directory,
    download_archive,
    get_release_asset_url,
    need_update,
    safe_extract_archive,
    validate_distribution,
)


class FakeResponse:
    def __init__(self, *, data=None, body=b"", headers=None, error=None):
        self._data = data
        self._body = body
        self.headers = headers or {}
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._data

    def iter_content(self, chunk_size):
        del chunk_size
        yield self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def make_zip(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_version_comparison_accepts_whitespace_and_rejects_bad_versions():
    assert not need_update("v0.3.1\n", "v0.3.1")
    assert need_update("v0.3.0", "0.3.1")
    assert need_update("v0.4.0", "0.3.1")
    with pytest.raises(ValueError):
        need_update("latest", "0.3.1")


def test_release_selects_named_asset_and_uses_timeout():
    response = FakeResponse(data={"assets": [
        {"name": "sources.zip", "browser_download_url": "https://github.com/example/sources.zip"},
        {"name": "dist.zip", "browser_download_url": "https://github.com/example/dist.zip"},
    ]})
    session = FakeSession(response)
    assert get_release_asset_url("fabiencomte", "editor", "v0.3.1", session=session).endswith("dist.zip")
    assert session.calls[0][1]["timeout"] == REQUEST_TIMEOUT


def test_release_rejects_missing_or_foreign_asset_url():
    session = FakeSession(FakeResponse(data={"assets": [
        {"name": "dist.zip", "browser_download_url": "https://evil.example/dist.zip"},
    ]}))
    with pytest.raises(UpdateError, match="invalid asset URL"):
        get_release_asset_url("fabiencomte", "editor", "v0.3.1", session=session)


def test_download_streams_to_destination_with_timeout(tmp_path):
    session = FakeSession(FakeResponse(body=b"zip", headers={"Content-Length": "3"}))
    destination = tmp_path / "dist.zip"
    download_archive("https://github.com/example/dist.zip", destination, session=session)
    assert destination.read_bytes() == b"zip"
    assert session.calls[0][1]["stream"] is True
    assert session.calls[0][1]["timeout"] == REQUEST_TIMEOUT


def test_download_rejects_oversized_content_length(tmp_path):
    session = FakeSession(FakeResponse(body=b"", headers={"Content-Length": str(100 * 1024 * 1024)}))
    with pytest.raises(UpdateError, match="larger than the safety limit"):
        download_archive("https://github.com/example/dist.zip", tmp_path / "dist.zip", session=session)


@pytest.mark.parametrize("member", ["../escape.txt", "folder/../../escape.txt", "C:/escape.txt", "..\\escape.txt"])
def test_safe_extract_rejects_zip_slip(tmp_path, member):
    archive = tmp_path / "bad.zip"
    make_zip(archive, {member: b"bad"})
    with pytest.raises(UpdateError, match="Unsafe archive path"):
        safe_extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_distribution_validation_and_atomic_replacement(tmp_path):
    old = tmp_path / "dist"
    old.mkdir()
    (old / "old.txt").write_text("old", encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "index.html").write_text("new", encoding="utf-8")
    (candidate / "version.txt").write_text("v0.3.1\n", encoding="utf-8")

    validate_distribution(candidate, "0.3.1")
    atomic_replace_directory(candidate, old)

    assert (old / "index.html").read_text(encoding="utf-8") == "new"
    assert not (old / "old.txt").exists()
    assert not list(tmp_path.glob(".dist.backup-*"))


def test_atomic_replacement_restores_old_distribution_on_failure(tmp_path, monkeypatch):
    old = tmp_path / "dist"
    old.mkdir()
    (old / "old.txt").write_text("old", encoding="utf-8")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "new.txt").write_text("new", encoding="utf-8")
    original_replace = Path.replace

    def fail_candidate_replace(path, target):
        if path == candidate:
            raise OSError("simulated activation failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_candidate_replace)
    with pytest.raises(UpdateError, match="Cannot activate"):
        atomic_replace_directory(candidate, old)

    assert (old / "old.txt").read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".dist.backup-*"))


def test_source_template_uses_jinja_json_filter():
    root = Path(__file__).parents[1]
    index = (root / "index.html").read_text(encoding="utf-8")
    assert "{{ data | tojson }}" in index
    assert "{{ data | safe }}" not in index

    environment = Environment(
        loader=FileSystemLoader(root),
        autoescape=select_autoescape(("html",)),
    )
    rendered = environment.get_template("index.html").render(
        data={"pose": "</script><script>alert(1)</script>", "image_url": ""}
    )
    assert "</script><script>alert(1)</script>" not in rendered
    assert "\\u003c/script\\u003e" in rendered
