from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient


def load_wrapper(monkeypatch, extension_dir: Path):
    modules = types.ModuleType("modules")
    callbacks = types.ModuleType("modules.script_callbacks")
    callbacks.on_app_started = lambda function: None
    modules.script_callbacks = callbacks
    modules.shared = types.SimpleNamespace(
        cmd_opts=types.SimpleNamespace(disable_openpose_editor_auto_update=True)
    )
    modules.scripts = types.SimpleNamespace(basedir=lambda: str(extension_dir))
    monkeypatch.setitem(sys.modules, "modules", modules)
    monkeypatch.setitem(sys.modules, "modules.script_callbacks", callbacks)

    script_path = Path(__file__).parents[1] / "scripts" / "openpose_editor.py"
    spec = importlib.util.spec_from_file_location("openpose_wrapper_test", script_path)
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    return wrapper


def test_fastapi_wrapper_serves_static_app_and_escapes_post_data(tmp_path, monkeypatch):
    source_root = Path(__file__).parents[1]
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        (source_root / "index.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (dist / "version.txt").write_text("v0.3.1", encoding="utf-8")
    wrapper = load_wrapper(monkeypatch, tmp_path)
    app = FastAPI()
    wrapper.mount_openpose_api(None, app)
    client = TestClient(app)

    assert client.get("/openpose_editor_index").status_code == 200
    assert client.get("/openpose_editor/version.txt").text == "v0.3.1"
    response = client.post(
        "/openpose_editor_index",
        json={
            "image_url": "data:image/png;base64,abc",
            "pose": "</script><script>alert(1)</script>",
        },
    )

    assert response.status_code == 200
    assert "</script><script>alert(1)</script>" not in response.text
    assert "\\u003c/script\\u003e" in response.text
