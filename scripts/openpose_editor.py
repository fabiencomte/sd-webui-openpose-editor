import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import gradio as gr
from pydantic import BaseModel, Field

import modules.script_callbacks as script_callbacks
from modules import shared, scripts
from openpose_editor_backend import (
    install_release,
    need_update,
    read_package_version,
    read_version_file,
)


class Item(BaseModel):
    # image url.
    image_url: str = Field(max_length=20_000_000)
    # stringified pose JSON.
    pose: str = Field(max_length=10_000_000)


EXTENSION_DIR = scripts.basedir()
DIST_DIR = os.path.join(EXTENSION_DIR, "dist")
RELEASE_OWNER = "fabiencomte"
RELEASE_REPO = "sd-webui-openpose-editor"


def update_app():
    """Install the exact frontend version expected by this checkout."""
    extension_dir = Path(EXTENSION_DIR)
    package_version = read_package_version(extension_dir)
    current_version = read_version_file(Path(DIST_DIR))
    if need_update(current_version, package_version):
        install_release(extension_dir, RELEASE_OWNER, RELEASE_REPO, package_version)


def mount_openpose_api(_: gr.Blocks, app: FastAPI):
    if not getattr(shared.cmd_opts, "disable_openpose_editor_auto_update", False):
        # Fail closed: serving a stale upstream bundle would silently discard
        # the Forge fixes implemented by the checked-out Python wrapper.
        update_app()

    templates = Jinja2Templates(directory=DIST_DIR)
    app.mount(
        "/openpose_editor",
        StaticFiles(directory=DIST_DIR, html=True),
        name="openpose_editor",
    )

    @app.get("/openpose_editor_index", response_class=HTMLResponse)
    async def index_get(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"data": {}},
        )

    @app.post("/openpose_editor_index", response_class=HTMLResponse)
    async def index_post(request: Request, item: Item):
        data = item.model_dump() if hasattr(item, "model_dump") else item.dict()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"data": data},
        )


script_callbacks.on_app_started(mount_openpose_api)
