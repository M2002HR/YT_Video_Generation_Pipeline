#!/usr/bin/env python3
"""Initialize service submodules and install runtime dependencies."""

from __future__ import annotations

import subprocess
import sys
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AJIL_REQUIREMENTS = ROOT / "services" / "ajil_uag" / "unified_gateway" / "requirements.txt"
ORDAK_REQUIREMENTS = ROOT / "services" / "ordak" / "requirements.txt"
ORDAK_VENV = ROOT / "services" / "ordak" / ".venv"
ORDAK_VENV_PYTHON = ORDAK_VENV / "bin" / "python"


def run(*args: str) -> None:
    print("+", " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)


def supported_python() -> str:
    for candidate in ("python3.13", "python3.12", "python3.11"):
        executable = shutil.which(candidate)
        if executable:
            return executable
    raise SystemExit(
        "Ordak requires Python 3.11+. Install a supported Python interpreter, "
        "then rerun this setup command."
    )


def main() -> None:
    run("git", "submodule", "sync", "--recursive")
    run("git", "submodule", "update", "--init", "--recursive")

    if not AJIL_REQUIREMENTS.exists():
        raise SystemExit(
            f"Ajil requirements not found after submodule init: {AJIL_REQUIREMENTS}"
        )
    if not ORDAK_REQUIREMENTS.exists():
        raise SystemExit(
            f"Ordak requirements not found after submodule init: {ORDAK_REQUIREMENTS}"
        )

    run(sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"))
    run(sys.executable, "-m", "pip", "install", "-r", str(AJIL_REQUIREMENTS))
    if not ORDAK_VENV_PYTHON.exists():
        run(supported_python(), "-m", "venv", str(ORDAK_VENV))
    version = subprocess.check_output(
        [str(ORDAK_VENV_PYTHON), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        text=True,
    ).strip()
    if tuple(map(int, version.split("."))) < (3, 11):
        raise SystemExit(f"Ordak virtualenv must use Python 3.11+, found {version}.")
    run(str(ORDAK_VENV_PYTHON), "-m", "pip", "install", "-r", str(ORDAK_REQUIREMENTS))

    print()
    print("Service setup complete.")
    print("If needed, create root config: cp .env.example .env")
    print("Start Ajil with: python scripts/run_ajil.py")
    print("Start Ordak with: python scripts/run_ordak.py")
    print("Check Ordak with: python scripts/check_ordak.py")


if __name__ == "__main__":
    main()
