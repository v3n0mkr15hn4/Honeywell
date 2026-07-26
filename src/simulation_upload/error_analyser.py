"""Parse EnergyPlus outputs without replacing the original diagnostic text."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class EnergyPlusErrorSummary:
    fatal_errors: list[str] = field(default_factory=list)
    severe_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recurring_warning_groups: dict[str, int] = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)
    missing_expected_files: list[str] = field(default_factory=list)
    original_error_log: str = ""

    @property
    def fatal_count(self) -> int:
        return len(self.fatal_errors)

    @property
    def severe_count(self) -> int:
        return len(self.severe_errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def to_dict(self, *, include_original: bool = False) -> dict[str, object]:
        data = asdict(self)
        if not include_original:
            data.pop("original_error_log", None)
        return data


class EnergyPlusErrorAnalyser:
    _CATEGORY_PATTERNS = {
        "weather_location_mismatch": re.compile(
            r"weather.*location|location.*weather", re.I
        ),
        "version_mismatch": re.compile(r"version.*(?:mismatch|invalid|newer|older)", re.I),
        "sizing_failure": re.compile(
            r"sizing.*(?:failed|failure|not complete)", re.I
        ),
        "convergence_issue": re.compile(r"converg|iteration limit", re.I),
        "missing_object_reference": re.compile(
            r"(?:not found|invalid reference|does not exist|missing object)", re.I
        ),
        "missing_file": re.compile(r"(?:file not found|could not open|missing file)", re.I),
    }

    @staticmethod
    def _messages(text: str, marker: str) -> list[str]:
        pattern = re.compile(
            rf"(?im)^\s*\*\*\s*{re.escape(marker)}\s*\*\*\s*(.+)$"
        )
        return [match.group(1).strip() for match in pattern.finditer(text)]

    @staticmethod
    def _warning_key(message: str) -> str:
        key = re.sub(r"\d+(?:\.\d+)?", "<n>", message.lower())
        key = re.sub(r"\s+", " ", key).strip()
        return key[:180]

    def analyse(self, output_dir: Path | str) -> EnergyPlusErrorSummary:
        root = Path(output_dir)
        summary = EnergyPlusErrorSummary()
        if not root.is_dir():
            summary.missing_expected_files.append("output directory")
            summary.categories.append("missing_file")
            return summary

        error_files = sorted(root.glob("*.err"))
        if not error_files:
            summary.missing_expected_files.append("EnergyPlus .err file")
            summary.categories.append("missing_file")
            return summary

        text = "\n\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in error_files
        )
        summary.original_error_log = text
        summary.fatal_errors = self._messages(text, "Fatal")
        summary.severe_errors = self._messages(text, "Severe")
        summary.warnings = self._messages(text, "Warning")
        groups = Counter(self._warning_key(item) for item in summary.warnings)
        summary.recurring_warning_groups = {
            key: count for key, count in groups.items() if count > 1
        }
        for category, pattern in self._CATEGORY_PATTERNS.items():
            if pattern.search(text):
                summary.categories.append(category)
        return summary
