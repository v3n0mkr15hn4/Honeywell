from __future__ import annotations

import io
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.simulation_upload.package_validator import (
    SimulationPackageValidator,
    UploadedFile,
)


IDF = b"Version, 26.1;\nBuilding, Demo;"
EPW = b"LOCATION,City,State,Country,Source,12345,1.0,2.0,3.0\n"


class PackageValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = SimulationPackageValidator()

    def validate(self, *files: tuple[str, bytes]):
        return self.validator.validate(
            [UploadedFile(name, content) for name, content in files]
        )

    def test_valid_idf_and_epw(self) -> None:
        result = self.validate(("model.idf", IDF), ("weather.epw", EPW))
        self.assertTrue(result.valid)
        self.assertEqual(result.detected_version, "26.1")

    def test_missing_or_duplicate_primary_files(self) -> None:
        missing = self.validate(("model.idf", IDF))
        duplicate = self.validate(
            ("one.idf", IDF), ("two.idf", IDF), ("weather.epw", EPW)
        )
        self.assertFalse(missing.valid)
        self.assertFalse(duplicate.valid)

    def test_executable_and_path_traversal_are_rejected(self) -> None:
        executable = self.validate(
            ("model.idf", IDF), ("weather.epw", EPW), ("payload.exe", b"MZ")
        )
        traversal = self.validate(
            ("../model.idf", IDF), ("weather.epw", EPW)
        )
        self.assertFalse(executable.valid)
        self.assertFalse(traversal.valid)

    def test_incompatible_version_is_rejected(self) -> None:
        result = self.validate(
            ("model.idf", b"Version, 25.2;"), ("weather.epw", EPW)
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.version_status, "incompatible")

    def test_missing_referenced_schedule_is_rejected(self) -> None:
        idf = (
            b"Version,26.1;\nSchedule:File, Test, Any Number, "
            b"missing.csv, 1, 0;"
        )
        result = self.validate(("model.idf", idf), ("weather.epw", EPW))
        self.assertFalse(result.valid)
        self.assertTrue(any("missing.csv" in item for item in result.errors))

    def test_zip_traversal_and_nested_archive_are_rejected(self) -> None:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("../model.idf", IDF)
            archive.writestr("weather.epw", EPW)
            archive.writestr("nested.zip", b"PK")
        result = self.validate(("package.zip", stream.getvalue()))
        self.assertFalse(result.valid)
        self.assertTrue(any("Unsafe ZIP path" in item for item in result.errors))
        self.assertTrue(any("Nested archive" in item for item in result.errors))

    def test_zip_expansion_limit_is_enforced_from_metadata(self) -> None:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("model.idf", IDF)
            archive.writestr("weather.epw", EPW)
            archive.writestr("large.txt", b"x" * 1024)
        validator = SimulationPackageValidator(max_expanded_bytes=100)
        result = validator.validate([UploadedFile("package.zip", stream.getvalue())])
        self.assertFalse(result.valid)
        self.assertTrue(any("expanded size" in item for item in result.errors))

    def test_zip_symbolic_link_is_rejected(self) -> None:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            link = zipfile.ZipInfo("linked.idf")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "target.idf")
            archive.writestr("weather.epw", EPW)
        result = self.validate(("package.zip", stream.getvalue()))
        self.assertFalse(result.valid)
        self.assertTrue(any("Symbolic link" in item for item in result.errors))

    def test_oversized_loose_file_is_rejected(self) -> None:
        validator = SimulationPackageValidator(max_file_bytes=10)
        result = validator.validate(
            [UploadedFile("model.idf", IDF), UploadedFile("weather.epw", EPW)]
        )
        self.assertFalse(result.valid)
        self.assertTrue(any("50 MB" in item for item in result.errors))


if __name__ == "__main__":
    unittest.main()
