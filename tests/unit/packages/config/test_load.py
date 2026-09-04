from pathlib import Path

from pydantic import BaseModel

from packages.config import load_yaml_config


class Sample(BaseModel):
    name: str
    port: int


def test_load_yaml_with_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SAMPLE_PORT", "9999")
    p = tmp_path / "s.yaml"
    p.write_text("name: hi\nport: ${SAMPLE_PORT}\n")
    cfg = load_yaml_config(p, Sample)
    assert cfg.name == "hi" and cfg.port == 9999
