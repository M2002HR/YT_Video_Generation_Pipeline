#!/usr/bin/env python3
"""Initialize service submodules and install runtime dependencies."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AJIL_REQUIREMENTS = ROOT / "services" / "ajil_uag" / "unified_gateway" / "requirements.txt"


def run(*args: str) -> None:
    print("+", " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    run("git", "submodule", "sync", "--recursive")
    run("git", "submodule", "update", "--init", "--recursive")

    if not AJIL_REQUIREMENTS.exists():
        raise SystemExit(
            f"Ajil requirements not found after submodule init: {AJIL_REQUIREMENTS}"
        )

    run(sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"))
    run(sys.executable, "-m", "pip", "install", "-r", str(AJIL_REQUIREMENTS))

    print()
    print("Service setup complete.")
    print("If needed, create root config: cp .env.example .env")
    print("Then start Ajil with: python scripts/run_ajil.py")


if __name__ == "__main__":
    main()
