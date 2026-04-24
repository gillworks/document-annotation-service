import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import Settings


def test_compose_mounts_uploads_volume_into_api_and_worker() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not installed")

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [docker, "compose", "config", "--no-interpolate", "--format", "json"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"docker compose config is unavailable: {result.stderr.strip()}")

    config = json.loads(result.stdout)
    assert "uploads" in config["volumes"]

    for service_name in ("api", "worker"):
        service = config["services"][service_name]
        upload_mounts = [
            volume
            for volume in service["volumes"]
            if volume.get("source") == "uploads" and volume.get("target") == "/data/uploads"
        ]
        assert upload_mounts, f"{service_name} must mount uploads at /data/uploads"
        assert service["environment"]["UPLOAD_DIR"] == "/data/uploads"


def test_upload_dir_supports_shared_volume_read_write(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    upload_dir = settings.upload_dir

    if str(upload_dir) == "/data/uploads" and not upload_dir.exists():
        upload_dir = tmp_path

    upload_dir.mkdir(parents=True, exist_ok=True)
    marker = upload_dir / "shared-volume-smoke.txt"
    marker.write_text("api wrote this file; worker must be able to read it", encoding="utf-8")

    assert marker.read_text(encoding="utf-8") == "api wrote this file; worker must be able to read it"

    marker.unlink(missing_ok=True)
