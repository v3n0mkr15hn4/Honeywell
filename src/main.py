"""Entry point for the modular EnergyPlus controller."""

from __future__ import annotations

from energyplus.runner import run_simulation


def main() -> int:
    """Run the closed-loop EnergyPlus controller."""

    return run_simulation()


if __name__ == "__main__":
    raise SystemExit(main())
