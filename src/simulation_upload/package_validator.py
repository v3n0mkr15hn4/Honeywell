"""Fail-closed validation for judge-supplied EnergyPlus packages."""

from __future__ import annotations

import io
import json
import re
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath


ALLOWED_EXTENSIONS = frozenset({".idf", ".epw", ".ddy", ".csv", ".json", ".txt"})
ARCHIVE_EXTENSION = ".zip"
MAX_COMPRESSED_BYTES = 50 * 1024 * 1024
MAX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_FILE_COUNT = 100

_VERSION_RE = re.compile(
    r"(?is)\bVersion\s*,\s*([0-9]+(?:\.[0-9]+){1,2})\s*;"
)
_SCHEDULE_BLOCK_RE = re.compile(r"(?is)(?:^|;)\s*Schedule:File\s*,(.*?);")
_CSV_TOKEN_RE = re.compile(r"(?i)([^,;\r\n]+\.csv)\s*(?:,|$)")
_CONTROL_RE = re.compile(r"[\x00-\x1f]")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class UploadedFile:
    name: str
    content: bytes


@dataclass(frozen=True)
class ValidatedFile:
    relative_path: str
    content: bytes
    encoding: str


@dataclass
class PackageValidationResult:
    valid: bool
    files: list[ValidatedFile] = field(default_factory=list)
    idf_path: str | None = None
    epw_path: str | None = None
    support_files: list[str] = field(default_factory=list)
    detected_version: str | None = None
    version_status: str = "unknown"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SimulationPackageValidator:
    """Validate uploads entirely in memory before any file is written."""

    def __init__(
        self,
        *,
        expected_version: str = "26.1.0",
        max_compressed_bytes: int = MAX_COMPRESSED_BYTES,
        max_expanded_bytes: int = MAX_EXPANDED_BYTES,
        max_file_bytes: int = MAX_FILE_BYTES,
        max_file_count: int = MAX_FILE_COUNT,
    ) -> None:
        self.expected_version = expected_version
        self.max_compressed_bytes = max_compressed_bytes
        self.max_expanded_bytes = max_expanded_bytes
        self.max_file_bytes = max_file_bytes
        self.max_file_count = max_file_count

    @staticmethod
    def _safe_name(name: str, *, archive_member: bool) -> str | None:
        normalized = name.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            not normalized
            or normalized.startswith(("/", "\\"))
            or _WINDOWS_DRIVE_RE.match(normalized)
            or path.is_absolute()
            or ".." in path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(part.startswith(".") for part in path.parts)
            or _CONTROL_RE.search(normalized)
        ):
            return None
        if not archive_member and len(path.parts) != 1:
            return None
        return path.as_posix()

    @staticmethod
    def _decode_text(content: bytes) -> tuple[str | None, str | None]:
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                return content.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        return None, None

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, int, int]:
        parts = [int(part) for part in value.split(".")]
        return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]

    def _expand_uploads(
        self, uploads: list[UploadedFile], result: PackageValidationResult
    ) -> list[UploadedFile]:
        if sum(len(item.content) for item in uploads) > self.max_compressed_bytes:
            result.errors.append("Total upload exceeds the 50 MB compressed limit.")
            return []

        expanded: list[UploadedFile] = []
        archive_count = sum(
            Path(item.name).suffix.lower() == ARCHIVE_EXTENSION for item in uploads
        )
        if archive_count and len(uploads) != 1:
            result.errors.append(
                "A ZIP package must be uploaded alone, not mixed with loose files."
            )
            return []
        if archive_count > 1:
            result.errors.append("Only one ZIP package is accepted.")
            return []

        for item in uploads:
            if Path(item.name).suffix.lower() != ARCHIVE_EXTENSION:
                expanded.append(item)
                continue
            try:
                with zipfile.ZipFile(io.BytesIO(item.content)) as archive:
                    members = [member for member in archive.infolist() if not member.is_dir()]
                    if len(members) > self.max_file_count:
                        result.errors.append("ZIP contains more than 100 files.")
                        return []
                    expanded_total = sum(member.file_size for member in members)
                    if expanded_total > self.max_expanded_bytes:
                        result.errors.append(
                            "ZIP expanded size exceeds the 200 MB limit."
                        )
                        return []
                    for member in members:
                        mode = member.external_attr >> 16
                        if stat.S_ISLNK(mode):
                            result.errors.append(
                                f"Symbolic link rejected: {member.filename}"
                            )
                            continue
                        safe_name = self._safe_name(
                            member.filename, archive_member=True
                        )
                        if safe_name is None:
                            result.errors.append(
                                f"Unsafe ZIP path rejected: {member.filename}"
                            )
                            continue
                        suffix = Path(safe_name).suffix.lower()
                        if suffix == ARCHIVE_EXTENSION:
                            result.errors.append(
                                f"Nested archive rejected: {safe_name}"
                            )
                            continue
                        if member.file_size > self.max_file_bytes:
                            result.errors.append(
                                f"File exceeds the 50 MB limit: {safe_name}"
                            )
                            continue
                        content = archive.read(member)
                        if len(content) != member.file_size:
                            result.errors.append(
                                f"ZIP size mismatch while extracting: {safe_name}"
                            )
                            continue
                        expanded.append(UploadedFile(safe_name, content))
            except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
                result.errors.append(f"Invalid ZIP package: {exc}")
        return expanded

    def validate(self, uploads: list[UploadedFile]) -> PackageValidationResult:
        result = PackageValidationResult(valid=False)
        if not uploads:
            result.errors.append("No files were uploaded.")
            return result

        expanded = self._expand_uploads(uploads, result)
        if result.errors:
            return result
        if len(expanded) > self.max_file_count:
            result.errors.append("Package contains more than 100 files.")
            return result
        if sum(len(item.content) for item in expanded) > self.max_expanded_bytes:
            result.errors.append("Expanded package exceeds the 200 MB limit.")
            return result

        seen: set[str] = set()
        decoded: dict[str, str] = {}
        for item in expanded:
            safe_name = self._safe_name(
                item.name, archive_member="/" in item.name.replace("\\", "/")
            )
            if safe_name is None:
                result.errors.append(f"Unsafe filename rejected: {item.name}")
                continue
            folded = safe_name.casefold()
            if folded in seen:
                result.errors.append(f"Duplicate filename rejected: {safe_name}")
                continue
            seen.add(folded)
            suffix = Path(safe_name).suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                result.errors.append(
                    f"File type {suffix or '<none>'} is not allowed: {safe_name}"
                )
                continue
            if len(item.content) > self.max_file_bytes:
                result.errors.append(
                    f"File exceeds the 50 MB limit: {safe_name}"
                )
                continue
            text, encoding = self._decode_text(item.content)
            if text is None or encoding is None:
                result.errors.append(f"Text decoding failed: {safe_name}")
                continue
            if encoding == "cp1252":
                result.warnings.append(
                    f"{safe_name} uses Windows-1252 rather than UTF-8."
                )
            decoded[safe_name] = text
            result.files.append(ValidatedFile(safe_name, item.content, encoding))
            if suffix == ".json":
                try:
                    metadata = json.loads(text)
                except json.JSONDecodeError as exc:
                    result.errors.append(
                        f"Invalid JSON metadata file {safe_name}: {exc.msg}"
                    )
                    continue
                if not isinstance(metadata, dict):
                    result.errors.append(
                        f"JSON metadata must contain one object: {safe_name}"
                    )

        idfs = [name for name in decoded if Path(name).suffix.lower() == ".idf"]
        epws = [name for name in decoded if Path(name).suffix.lower() == ".epw"]
        if len(idfs) != 1:
            result.errors.append(
                f"Exactly one primary IDF is required; found {len(idfs)}."
            )
        if len(epws) != 1:
            result.errors.append(
                f"Exactly one EPW is required; found {len(epws)}."
            )
        if result.errors:
            return result

        result.idf_path, result.epw_path = idfs[0], epws[0]
        result.support_files = sorted(
            name for name in decoded if name not in {result.idf_path, result.epw_path}
        )
        idf_text = decoded[result.idf_path]
        epw_text = decoded[result.epw_path]

        version_match = _VERSION_RE.search(idf_text)
        if version_match:
            result.detected_version = version_match.group(1)
            result.version_status = (
                "compatible"
                if self._version_tuple(result.detected_version)
                == self._version_tuple(self.expected_version)
                else "incompatible"
            )
            if result.version_status == "incompatible":
                result.errors.append(
                    "IDF version "
                    f"{result.detected_version} is incompatible with the configured "
                    f"EnergyPlus {self.expected_version} server. Upgrade explicitly; "
                    "the upload will not be edited silently."
                )
        else:
            result.version_status = "unknown"
            result.warnings.append(
                "IDF Version object was not detected. MCP validation may inspect it, "
                "but simulation remains disabled until compatibility is established."
            )

        first_epw_line = epw_text.splitlines()[0] if epw_text.splitlines() else ""
        if not first_epw_line.upper().startswith("LOCATION,") or len(
            first_epw_line.split(",")
        ) < 8:
            result.errors.append("EPW header is not a plausible LOCATION record.")

        referenced_csvs: set[str] = set()
        without_comments = re.sub(r"![^\r\n]*", "", idf_text)
        for match in _SCHEDULE_BLOCK_RE.finditer(without_comments):
            for csv_match in _CSV_TOKEN_RE.finditer(match.group(1)):
                referenced_csvs.add(
                    csv_match.group(1).strip().strip("\"'").replace("\\", "/")
                )
        available = {name.casefold() for name in decoded}
        available_basenames = {Path(name).name.casefold() for name in decoded}
        for reference in sorted(referenced_csvs):
            if (
                reference.casefold() not in available
                and Path(reference).name.casefold() not in available_basenames
            ):
                result.errors.append(
                    f"Referenced Schedule:File CSV is missing: {reference}"
                )

        result.valid = not result.errors and result.version_status == "compatible"
        return result
