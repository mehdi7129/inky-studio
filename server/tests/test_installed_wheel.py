"""Build and install a real wheel in isolation; import no application runtime."""
from __future__ import annotations

import configparser
import json
import os
import shutil
import subprocess
import sys
import tomllib
import venv
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement

SERVER = Path(__file__).resolve().parents[1]


def _run(arguments, *, cwd, env=None):
    completed = subprocess.run(arguments, cwd=cwd, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout


def test_installed_wheel_keeps_frontend_outside_site_packages(tmp_path):
    """Hatchling must deliver the guarded modules, metadata and factory path."""
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(SERVER / name, source / name)
    shutil.copytree(SERVER / "inky_web", source / "inky_web",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    dist = tmp_path / "dist"
    _run([sys.executable, "-m", "hatchling", "build", "--target", "wheel", "--directory", str(dist)],
         cwd=source)
    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]
    project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert {
            "inky_web/__init__.py", "inky_web/main.py", "inky_web/frontend.py",
            "inky_web/provisioning/factory_environment.py",
            "inky_web/provisioning/factory_writer.py",
            "inky_web/provisioning/factory_runtime.py",
            "inky_web/provisioning/factory_phase_a.py",
            "inky_web/provisioning/connected_peer.py",
        } <= names
        assert not any(name.endswith((".pth", ".egg-link", ".pyc"))
                       or "__editable__" in name or name.endswith("direct_url.json") for name in names)
        metadata_path, = (name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_path).decode())
        assert metadata["Name"] == project["name"]
        assert metadata["Version"] == project["version"]
        assert metadata["Requires-Python"] == project["requires-python"]
        assert metadata["Author"] == "Inky Studio contributors"
        assert metadata["Author-email"] is None
        assert metadata["Maintainer-email"] is None
        assert "@" not in str(metadata)
        runtime = {str(Requirement(value)) for value in metadata.get_all("Requires-Dist")
                   if Requirement(value).marker is None}
        assert runtime == {str(Requirement(value)) for value in project["dependencies"]}
        pi = [Requirement(value) for value in metadata.get_all("Requires-Dist")
              if Requirement(value).marker is not None
              and Requirement(value).marker.evaluate({"extra": "pi"})]
        assert {str(value.specifier) for value in pi if value.name == "inky"} == {"==2.3.0"}
        entry_points = configparser.ConfigParser()
        entry_points.read_string(archive.read(metadata_path.replace("METADATA", "entry_points.txt")).decode())
        assert entry_points["console_scripts"]["inky-studio-server"] == "inky_web.main:run"

    installed = tmp_path / "installed"
    venv.EnvBuilder(with_pip=True).create(installed)
    python = installed / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    clean_env = {name: value for name, value in os.environ.items()
                 if name not in {"PYTHONPATH", "PYTHONHOME", "INKY_STUDIO_FACTORY_REQUIRED"}
                 and not name.startswith("INKYOS_WRITER_")}
    _run([str(python), "-I", "-m", "pip", "install", "--no-index", "--no-deps", "--no-compile",
          "--disable-pip-version-check", "--no-cache-dir", str(wheel)], cwd=tmp_path, env=clean_env)
    clean_env["INKY_STUDIO_FACTORY_REQUIRED"] = "1"
    probe = _run([str(python), "-I", "-c", """
import json
import sys
from pathlib import Path
from inky_web import frontend
module = Path(frontend.__file__).resolve()
decoy = module.parents[2] / "client" / "dist"
decoy.mkdir(parents=True)
(decoy / "index.html").write_text("WRONG SITE-PACKAGES FRONTEND")
print(json.dumps({"module": str(module), "frontend": str(frontend.resolve_client_dist(module)),
                  "decoy": str(decoy), "app_runtime_imported": "inky_web.main" in sys.modules}))
"""], cwd=tmp_path, env=clean_env)
    result = json.loads(probe)
    module = Path(result["module"])
    assert module.is_relative_to(installed)
    assert "site-packages" in module.parts
    assert not module.is_relative_to(source)
    assert result["frontend"] == "/usr/lib/inky-studio/client/dist"
    assert result["frontend"] != result["decoy"]
    assert result["app_runtime_imported"] is False
    assert not list(installed.rglob("__editable__*"))
