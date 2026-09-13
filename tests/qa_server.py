#!/usr/bin/env python3
import importlib.util
from pathlib import Path

from flask import send_from_directory

project = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("little_sounds_app", project / "server" / "app.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
app = module.app


@app.get("/")
@app.get("/<path:name>")
def test_static(name=""):
    candidate = project / "site" / name
    if candidate.is_dir():
        name = f"{name.rstrip('/')}/index.html"
    elif not name:
        name = "index.html"
    return send_from_directory(project / "site", name)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765)
