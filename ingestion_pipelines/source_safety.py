"""Source registration and safety checks for the ingestion boundary.

This module deliberately returns metadata and marker categories, never source
content. It is the cheap trust-boundary check before a modality extractor runs.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pipelines.common.ntro_policy import require_classification

from ingestion_pipelines.extract import (
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
    PPTX_EXTENSIONS,
    TEXT_EXTENSIONS,
    VIDEO_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
)


class SourceSafetyError(ValueError):
    """Raised when a source cannot cross the ingestion trust boundary."""


@dataclass(frozen=True, slots=True)
class SourceInspection:
    source_reference: str
    source_hash: str
    byte_size: int
    media_type: str
    modality: str
    classification_level: str
    user_id: str | None
    case_id: str | None
    task_id: str | None
    instruction_markers: tuple[str, ...] = ()


_INSTRUCTION_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore-previous-instructions", re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I)),
    ("role-spoofing", re.compile(r"(?:system|developer|assistant)\s+message\s*[:>]", re.I)),
    ("prompt-disclosure", re.compile(r"(?:reveal|print|show|leak)\s+(?:the\s+)?(?:system\s+)?prompt", re.I)),
    ("tool-or-command-request", re.compile(r"(?:run|execute)\s+(?:this\s+)?(?:command|tool|script)", re.I)),
)

_MEDIA_TYPES = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pptm": "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
    ".ppsx": "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
    ".ppsm": "application/vnd.ms-powerpoint.slideshow.macroEnabled.12",
    ".potx": "application/vnd.openxmlformats-officedocument.presentationml.template",
    ".potm": "application/vnd.ms-powerpoint.template.macroEnabled.12",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _modality(extension: str) -> str:
    if extension in TEXT_EXTENSIONS:
        return "text"
    if extension in PDF_EXTENSIONS:
        return "pdf"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in PPTX_EXTENSIONS:
        return "pptx"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    raise SourceSafetyError(f"Unsupported file type: {extension or '<none>'}")


def _looks_like_text(sample: bytes) -> bool:
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _matches_magic(path: Path, extension: str, sample: bytes, *, max_uncompressed_bytes: int) -> bool:
    if extension in TEXT_EXTENSIONS:
        return _looks_like_text(sample)
    if extension in PDF_EXTENSIONS:
        return sample.startswith(b"%PDF-")
    if extension in {".png"}:
        return sample.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return sample.startswith(b"\xff\xd8\xff")
    if extension in {".gif"}:
        return sample.startswith((b"GIF87a", b"GIF89a"))
    if extension in {".webp"}:
        return len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"WEBP"
    if extension in {".bmp"}:
        return sample.startswith(b"BM")
    if extension in {".tif", ".tiff"}:
        return sample.startswith((b"II*\x00", b"MM\x00*"))
    if extension in PPTX_EXTENSIONS:
        if not sample.startswith(b"PK"):
            return False
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
        except (OSError, zipfile.BadZipFile):
            return False
        if len(infos) > 4096:
            return False
        if sum(info.file_size for info in infos) > max_uncompressed_bytes:
            return False
        names = {info.filename for info in infos}
        if any(
            Path(name).is_absolute() or ".." in Path(name).parts
            for name in names
        ):
            return False
        return "[Content_Types].xml" in names and any(name.startswith("ppt/") for name in names)
    if extension in VIDEO_EXTENSIONS:
        if extension in {".mp4", ".mov"}:
            return len(sample) >= 12 and sample[4:8] == b"ftyp"
        if extension == ".avi":
            return len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"AVI "
        if extension in {".mkv", ".webm"}:
            return sample.startswith(b"\x1a\x45\xdf\xa3")
    return False


def _instruction_markers(path: Path, extension: str) -> tuple[str, ...]:
    if extension not in TEXT_EXTENSIONS:
        return ()
    with path.open("rb") as source:
        text = source.read(1024 * 1024).decode("utf-8", errors="ignore")
    return tuple(label for label, pattern in _INSTRUCTION_MARKERS if pattern.search(text))


def inspect_source(
    file_path: str,
    *,
    source_reference: str,
    max_bytes: int,
    classification_level: str = "RESTRICTED",
    user_id: str | None = None,
    case_id: str | None = None,
    task_id: str | None = None,
) -> SourceInspection:
    """Validate and fingerprint a source without returning its content."""

    path = Path(file_path)
    if not path.is_file():
        raise SourceSafetyError("source file is not available")
    if max_bytes < 1:
        raise SourceSafetyError("max_bytes must be positive")
    reference = str(source_reference or "").strip()
    if not reference or Path(reference).name != reference or any(ord(char) < 32 for char in reference):
        raise SourceSafetyError("source_reference must be a safe filename")

    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise SourceSafetyError(f"Unsupported file type: {extension or '<none>'}")
    byte_size = path.stat().st_size
    if byte_size > max_bytes:
        raise SourceSafetyError("source exceeds the configured size limit")

    with path.open("rb") as source:
        sample = source.read(4096)
    if not _matches_magic(path, extension, sample, max_uncompressed_bytes=max_bytes):
        raise SourceSafetyError("source content does not match its declared file type")

    classification = require_classification(classification_level)
    return SourceInspection(
        source_reference=reference,
        source_hash=_sha256(path),
        byte_size=byte_size,
        media_type=_MEDIA_TYPES.get(extension) or mimetypes.guess_type(reference)[0] or "application/octet-stream",
        modality=_modality(extension),
        classification_level=classification,
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
        instruction_markers=_instruction_markers(path, extension),
    )
