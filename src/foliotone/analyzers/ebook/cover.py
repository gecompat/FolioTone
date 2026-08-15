"""FolioTone-owned perceptual fingerprinting for extracted e-book covers."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from io import BytesIO
from typing import cast

from PIL import Image, ImageOps, UnidentifiedImageError
from PIL import __version__ as PILLOW_VERSION

from foliotone.core import EntityId, EntityKind, FileObservation, Fingerprint
from foliotone.tooling import ToolExecution

DEFAULT_MAX_EBOOK_COVER_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_EBOOK_COVER_PIXELS = 40_000_000
COVER_FINGERPRINT_KIND = "EBOOK_COVER_DHASH"
COVER_FINGERPRINT_PROFILE = (
    f"horizontal-luma-9x8-lanczos-v1+pillow-{PILLOW_VERSION}"
)
SUPPORTED_COVER_IMAGE_FORMATS = ("GIF", "JPEG", "PNG", "WEBP")
_SUPPORTED_COVER_IMAGE_FORMAT_SET = frozenset(SUPPORTED_COVER_IMAGE_FORMATS)


class EbookCoverError(ValueError):
    """An extracted cover cannot satisfy the bounded image contract."""


@dataclass(frozen=True, slots=True)
class EbookCoverFingerprint:
    """Normalized image facts plus a deterministic 64-bit difference hash."""

    image_format: str
    width: int
    height: int
    value: str


def fingerprint_ebook_cover(
    data: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_EBOOK_COVER_BYTES,
    max_pixels: int = DEFAULT_MAX_EBOOK_COVER_PIXELS,
) -> EbookCoverFingerprint:
    """Decode one bounded raster cover and calculate horizontal dHash v1."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if max_pixels <= 0:
        raise ValueError("max_pixels must be positive")
    if not data:
        raise EbookCoverError("e-book cover is empty")
    if len(data) > max_bytes:
        raise EbookCoverError("e-book cover exceeds the configured size limit")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=SUPPORTED_COVER_IMAGE_FORMATS) as image:
                image_format = (image.format or "").upper()
                if image_format not in _SUPPORTED_COVER_IMAGE_FORMAT_SET:
                    raise EbookCoverError("e-book cover uses an unsupported image format")
                if image.width <= 0 or image.height <= 0:
                    raise EbookCoverError("e-book cover has invalid dimensions")
                if image.width * image.height > max_pixels:
                    raise EbookCoverError("e-book cover exceeds the configured pixel limit")

                image.seek(0)
                with ImageOps.exif_transpose(image) as oriented:
                    width, height = oriented.size
                    with oriented.convert("L") as grayscale:
                        with grayscale.resize(
                            (9, 8),
                            Image.Resampling.LANCZOS,
                            reducing_gap=3.0,
                        ) as sample:
                            pixels = sample.load()
                            if pixels is None:
                                raise EbookCoverError("e-book cover could not be decoded")
                            bits = 0
                            for y in range(8):
                                for x in range(8):
                                    bits = (bits << 1) | int(
                                        cast(int, pixels[x, y])
                                        > cast(int, pixels[x + 1, y])
                                    )
    except EbookCoverError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as error:
        raise EbookCoverError("e-book cover is not a supported safe raster image") from error

    return EbookCoverFingerprint(
        image_format=image_format,
        width=width,
        height=height,
        value=f"{bits:016x}",
    )


def build_cover_fingerprint(
    normalized: EbookCoverFingerprint,
    observation: FileObservation,
    execution: ToolExecution,
) -> Fingerprint:
    """Attach cover-similarity Evidence to the exact observation and extraction."""
    if execution.finished_at is None:
        raise EbookCoverError("successful cover extraction has no completion time")
    return Fingerprint(
        id=EntityId.new(),
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=observation.id,
        kind=COVER_FINGERPRINT_KIND,
        algorithm="dhash-64",
        algorithm_version=COVER_FINGERPRINT_PROFILE,
        value=normalized.value,
        created_at=execution.finished_at,
        tool_execution_id=execution.id,
    )
