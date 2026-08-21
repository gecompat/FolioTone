"""Non-mutating readiness checks for the local e-book specialist toolchain."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from foliotone.adapters.calibre.common import calibre_version_policy
from foliotone.adapters.epubcheck.validation import epubcheck_version_policy
from foliotone.adapters.poppler.pdf import poppler_version_policy

EBOOK_TOOLCHAIN_DOCTOR_PROFILE = "ebook-toolchain-doctor/v1"
EBOOK_TOOLCHAIN_LINUX_AMD64_PROFILE = "ebook-toolchain-linux-amd64/v1"
MAX_VERSION_OUTPUT_BYTES = 64 * 1024
VERSION_TIMEOUT_SECONDS = 15.0

_CALIBRE_VERSION_PATTERN = re.compile(
    r"\bcalibre\s+(?P<version>\d+[.]\d+(?:[.]\d+)?)",
    re.IGNORECASE,
)
_POPPLER_VERSION_PATTERN = re.compile(
    r"\b(?:pdfinfo|pdftotext)\s+version\s+(?P<version>\d+[.]\d+(?:[.]\d+)?)",
    re.IGNORECASE,
)
_EPUBCHECK_VERSION_PATTERN = re.compile(
    r"\bEPUBCheck\s+v(?P<version>\d+[.]\d+[.]\d+)\b",
    re.IGNORECASE,
)
_JAVA_VERSION_PATTERN = re.compile(
    r'\bversion\s+"(?P<version>\d+(?:[.]\d+)*)"',
    re.IGNORECASE,
)
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class VersionCommandResult:
    """Bounded result of one no-shell version command."""

    returncode: int
    stdout: str
    stderr: str


VersionRunner = Callable[[tuple[str, ...]], VersionCommandResult]
ExecutableResolver = Callable[[str], str | None]
VersionPolicy = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class EbookToolReadiness:
    """One specialist executable or artifact readiness result."""

    tool: str
    status: str
    version: str | None = None
    reason: str | None = None

    @property
    def ready(self) -> bool:
        """Return whether this tool satisfies its adapter contract."""
        return self.status == "READY"

    def as_dict(self) -> dict[str, str | bool | None]:
        """Return the stable path-free JSON projection."""
        return {
            "tool": self.tool,
            "status": self.status,
            "ready": self.ready,
            "version": self.version,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class EbookFormatReadiness:
    """Readiness of every required tool for one supported e-book format."""

    format: str
    status: str
    required_tools: tuple[str, ...]
    unavailable_tools: tuple[str, ...]

    @property
    def ready(self) -> bool:
        """Return whether every required specialist is ready."""
        return self.status == "READY"

    def as_dict(self) -> dict[str, str | bool | list[str]]:
        """Return the stable JSON projection."""
        return {
            "format": self.format,
            "status": self.status,
            "ready": self.ready,
            "required_tools": list(self.required_tools),
            "unavailable_tools": list(self.unavailable_tools),
        }


@dataclass(frozen=True, slots=True)
class EbookToolchainReadinessReport:
    """Path-free Doctor report for tools and format-specific readiness."""

    profile: str
    provisioned_profile: str
    tools: tuple[EbookToolReadiness, ...]
    formats: tuple[EbookFormatReadiness, ...]

    @property
    def ready(self) -> bool:
        """Return whether all currently supported formats are ready."""
        return all(item.ready for item in self.formats)

    def as_dict(self) -> dict[str, object]:
        """Return a deterministic machine-readable report."""
        return {
            "profile": self.profile,
            "provisioned_profile": self.provisioned_profile,
            "status": "READY" if self.ready else "NOT_READY",
            "ready": self.ready,
            "tools": [tool.as_dict() for tool in self.tools],
            "formats": [item.as_dict() for item in self.formats],
        }


def inspect_ebook_toolchain(
    *,
    ebook_meta_executable: str = "ebook-meta",
    ebook_convert_executable: str = "ebook-convert",
    calibre_debug_executable: str = "calibre-debug",
    pdfinfo_executable: str = "pdfinfo",
    pdftotext_executable: str = "pdftotext",
    java_executable: str = "java",
    epubcheck_jar: Path = Path("epubcheck.jar"),
    provisioned_profile: str | None = None,
    runner: VersionRunner | None = None,
    resolver: ExecutableResolver | None = None,
) -> EbookToolchainReadinessReport:
    """Probe fixed tool versions without opening media or installing anything."""
    run = runner or _run_version_command
    resolve = resolver or _resolve_executable
    tools = (
        _probe_executable(
            "ebook-meta",
            ebook_meta_executable,
            ("--version",),
            calibre_version_policy,
            run,
            resolve,
        ),
        _probe_executable(
            "ebook-convert",
            ebook_convert_executable,
            ("--version",),
            calibre_version_policy,
            run,
            resolve,
        ),
        _probe_executable(
            "calibre-debug",
            calibre_debug_executable,
            ("--version",),
            calibre_version_policy,
            run,
            resolve,
        ),
        _probe_executable(
            "pdfinfo",
            pdfinfo_executable,
            ("-v",),
            poppler_version_policy,
            run,
            resolve,
        ),
        _probe_executable(
            "pdftotext",
            pdftotext_executable,
            ("-v",),
            poppler_version_policy,
            run,
            resolve,
        ),
        _probe_executable(
            "java",
            java_executable,
            ("-version",),
            _java_version_policy,
            run,
            resolve,
        ),
        _probe_epubcheck(epubcheck_jar, java_executable, run, resolve),
    )
    by_name = {tool.tool: tool for tool in tools}
    formats = tuple(
        _format_readiness(format_name, required, by_name)
        for format_name, required in (
            (
                "EPUB",
                (
                    "ebook-meta",
                    "ebook-convert",
                    "calibre-debug",
                    "java",
                    "epubcheck",
                ),
            ),
            ("MOBI", ("ebook-meta", "ebook-convert", "calibre-debug")),
            ("AZW", ("ebook-meta", "ebook-convert", "calibre-debug")),
            ("AZW3", ("ebook-meta", "ebook-convert", "calibre-debug")),
            ("PDF", ("pdfinfo", "pdftotext")),
        )
    )
    requested_profile = provisioned_profile or os.environ.get(
        "FOLIOTONE_EBOOK_TOOLCHAIN_PROFILE",
        "UNMANAGED_LOCAL",
    )
    reported_profile = (
        EBOOK_TOOLCHAIN_LINUX_AMD64_PROFILE
        if requested_profile == EBOOK_TOOLCHAIN_LINUX_AMD64_PROFILE
        else "UNMANAGED_LOCAL"
    )
    return EbookToolchainReadinessReport(
        profile=EBOOK_TOOLCHAIN_DOCTOR_PROFILE,
        provisioned_profile=reported_profile,
        tools=tools,
        formats=formats,
    )


def _probe_epubcheck(
    jar: Path,
    java_executable: str,
    runner: VersionRunner,
    resolver: ExecutableResolver,
) -> EbookToolReadiness:
    try:
        resolved_java = resolver(java_executable)
    except OSError:
        return EbookToolReadiness("epubcheck", "FAILED", reason="java resolution failed")
    if resolved_java is None:
        return EbookToolReadiness("epubcheck", "MISSING", reason="java executable is missing")
    try:
        resolved_jar = jar.expanduser().resolve()
    except (OSError, RuntimeError):
        return EbookToolReadiness("epubcheck", "MISSING", reason="EPUBCheck JAR is missing")
    if not resolved_jar.is_file():
        return EbookToolReadiness("epubcheck", "MISSING", reason="EPUBCheck JAR is missing")
    return _evaluate_version_command(
        "epubcheck",
        (resolved_java, "-jar", str(resolved_jar), "--version"),
        epubcheck_version_policy,
        runner,
    )


def _probe_executable(
    tool: str,
    executable: str,
    version_args: tuple[str, ...],
    policy: VersionPolicy,
    runner: VersionRunner,
    resolver: ExecutableResolver,
) -> EbookToolReadiness:
    try:
        resolved = resolver(executable)
    except OSError:
        return EbookToolReadiness(tool, "FAILED", reason="executable resolution failed")
    if resolved is None:
        return EbookToolReadiness(tool, "MISSING", reason="executable is missing")
    return _evaluate_version_command(tool, (resolved, *version_args), policy, runner)


def _evaluate_version_command(
    tool: str,
    argv: tuple[str, ...],
    policy: VersionPolicy,
    runner: VersionRunner,
) -> EbookToolReadiness:
    try:
        result = runner(argv)
    except (OSError, subprocess.SubprocessError):
        return EbookToolReadiness(
            tool,
            "FAILED",
            reason="version command could not be completed",
        )
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    version = _normalized_version(tool, combined)
    if result.returncode != 0:
        return EbookToolReadiness(
            tool,
            "FAILED",
            version=version,
            reason=f"version command exited with code {result.returncode}",
        )
    policy_error = policy(combined)
    if policy_error is not None:
        return EbookToolReadiness(
            tool,
            "INCOMPATIBLE",
            version=version,
            reason=_safe_summary(policy_error),
        )
    return EbookToolReadiness(tool, "READY", version=version)


def _format_readiness(
    format_name: str,
    required: tuple[str, ...],
    tools: Mapping[str, EbookToolReadiness],
) -> EbookFormatReadiness:
    unavailable = tuple(tool for tool in required if not tools[tool].ready)
    return EbookFormatReadiness(
        format=format_name,
        status="READY" if not unavailable else "NOT_READY",
        required_tools=required,
        unavailable_tools=unavailable,
    )


def _java_version_policy(version_text: str) -> str | None:
    match = _JAVA_VERSION_PATTERN.search(version_text)
    if match is None:
        return "Java version is unrecognized"
    if int(match.group("version").split(".", maxsplit=1)[0]) < 11:
        return "Java 11 or newer is required"
    return None


def _normalized_version(tool: str, version_text: str) -> str | None:
    if tool in {"ebook-meta", "ebook-convert", "calibre-debug"}:
        pattern = _CALIBRE_VERSION_PATTERN
    elif tool in {"pdfinfo", "pdftotext"}:
        pattern = _POPPLER_VERSION_PATTERN
    elif tool == "epubcheck":
        pattern = _EPUBCHECK_VERSION_PATTERN
    elif tool == "java":
        pattern = _JAVA_VERSION_PATTERN
    else:
        return None
    match = pattern.search(version_text)
    return match.group("version") if match is not None else None


def _resolve_executable(executable: str) -> str | None:
    candidate = executable.strip()
    if not candidate:
        return None
    return shutil.which(candidate)


def _run_version_command(argv: tuple[str, ...]) -> VersionCommandResult:
    process = subprocess.Popen(  # noqa: S603 - fixed no-shell argv after explicit resolution
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout = bytearray()
    stderr = bytearray()
    rejected = threading.Event()

    def capture(stream: BinaryIO, target: bytearray) -> None:
        try:
            while chunk := os.read(stream.fileno(), 8192):
                if len(target) + len(chunk) > MAX_VERSION_OUTPUT_BYTES:
                    rejected.set()
                    process.kill()
                    return
                target.extend(chunk)
        except (OSError, ValueError):
            rejected.set()
            try:
                process.kill()
            except OSError:
                pass

    readers = (
        threading.Thread(target=capture, args=(process.stdout, stdout)),
        threading.Thread(target=capture, args=(process.stderr, stderr)),
    )
    for reader in readers:
        reader.start()
    try:
        returncode = process.wait(timeout=VERSION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        raise subprocess.TimeoutExpired(argv, VERSION_TIMEOUT_SECONDS) from error
    finally:
        for reader in readers:
            reader.join()
    if rejected.is_set():
        raise subprocess.SubprocessError("version output exceeded the 64 KiB limit")
    return VersionCommandResult(
        returncode=returncode,
        stdout=bytes(stdout).decode("utf-8", errors="replace"),
        stderr=bytes(stderr).decode("utf-8", errors="replace"),
    )


def _safe_summary(value: str) -> str:
    first_line = next((line.strip() for line in value.splitlines() if line.strip()), "")
    return _CONTROL_PATTERN.sub("?", first_line)[:240]
