#!/usr/bin/env python3
"""Fail when generated files no longer match the OpenAPI spec.

Used by pre-commit and CI so ``enums.py`` and ``translations/en.json`` cannot
drift away from ``resources/openapi.json`` or from the entity descriptions.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

GENERATED = {
    "scripts/generate_enums.py": "custom_components/polestar_data_portal/enums.py",
    "scripts/generate_translations.py": (
        "custom_components/polestar_data_portal/translations/en.json"
    ),
}


def main() -> int:
    """Regenerate each file and report any that changed."""
    stale: list[str] = []
    skipped: list[str] = []

    for generator, target in GENERATED.items():
        path = REPO / target
        before = path.read_text() if path.exists() else None

        result = subprocess.run(
            [sys.executable, generator],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            if "No module named 'homeassistant'" in result.stderr:
                # Generating the translations needs the entity descriptions,
                # which import Home Assistant. Rather than make pre-commit
                # unusable without the test dependencies installed, skip it
                # here and let CI, which installs them, be the real gate.
                skipped.append(target)
                continue
            print(f"{generator} failed:\n{result.stderr}", file=sys.stderr)
            return result.returncode

        if before is not None and path.read_text() != before:
            stale.append(f"  {target}  (run: python3 {generator})")

    if skipped:
        print(
            "Skipped (Home Assistant not importable; CI checks these):\n  "
            + "\n  ".join(skipped),
            file=sys.stderr,
        )

    if stale:
        print("Generated files are out of date:", file=sys.stderr)
        print("\n".join(stale), file=sys.stderr)
        print(
            "\nThey have been regenerated in place; review and commit them.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
