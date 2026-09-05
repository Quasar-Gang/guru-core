"""Export the API service's OpenAPI document to docs/api/.

    uv run python scripts/export_openapi.py

Writes both JSON and YAML. The document is generated from the running app, not
written by hand, so it cannot drift from the routes: every path, model and status
code comes from the code that serves it.

Swagger UI and ReDoc are also served live at /docs and /redoc; the exported files
exist for tooling that wants the spec without booting the service — client
generators, API gateways, review diffs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from services.api.adapters.http.app import create_app
from services.api.container import build_test_container

OUT = Path(__file__).resolve().parent.parent / "docs" / "api"


def build_spec() -> dict[str, Any]:
    """The spec of the real app, assembled with fakes so nothing needs a database."""
    spec: dict[str, Any] = create_app(build_test_container()).openapi()
    spec["servers"] = [
        {"url": "http://127.0.0.1:8000", "description": "Local development"},
    ]
    return spec


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    spec = build_spec()

    json_path = OUT / "openapi.json"
    json_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    yaml_path = OUT / "openapi.yaml"
    yaml_path.write_text(
        yaml.safe_dump(spec, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8"
    )

    endpoints = sum(len(ops) for ops in spec["paths"].values())
    schemas = len(spec.get("components", {}).get("schemas", {}))
    print(f"wrote {json_path.relative_to(OUT.parent.parent)} and {yaml_path.name}")
    print(f"  {endpoints} endpoints, {schemas} schemas, {len(spec.get('tags', []))} tags")


if __name__ == "__main__":
    main()
