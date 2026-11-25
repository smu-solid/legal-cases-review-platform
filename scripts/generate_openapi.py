"""Generate or verify the deterministic public API snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from review_platform.main import create_app  # noqa: E402
from review_platform.settings import Settings  # noqa: E402

OUTPUT = Path("packages/contracts/openapi/openapi-v1.json")


def rendered_openapi() -> str:
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=None,
            session_hmac_key="openapi-session-key-00000000000000000000",
            activation_hmac_key="openapi-activation-key-000000000000000000",
        )
    )
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    rendered = rendered_openapi()
    if arguments.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
            raise SystemExit("OpenAPI snapshot is stale; run scripts/generate_openapi.py")
        return
    OUTPUT.write_text(rendered)


if __name__ == "__main__":
    main()
