#!/usr/bin/env python3
"""Generate and verify the fixed archive-image provenance and public manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
GITHUB_WORKFLOW_BUILD_TYPE = "https://actions.github.io/buildtypes/workflow/v1"
GITHUB_WORKFLOW_BUILDER_ID = (
    "https://github.com/gecompat/FolioTone/.github/workflows/"
    "archive-image.yml@refs/heads/main"
)
GITHUB_REPOSITORY_ID = "1328118830"
GITHUB_REPOSITORY_OWNER_ID = "48807214"
IMAGE_NAME = "ghcr.io/gecompat/foliotone-archive-7zip"
MANIFEST_DIGEST = "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
MANIFEST_SIZE = 838
MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
REGISTRY_REALM = "https://ghcr.io/token"
REGISTRY_SERVICE = "ghcr.io"
REGISTRY_SCOPE = "repository:gecompat/foliotone-archive-7zip:pull"
MANIFEST_URL = f"https://ghcr.io/v2/gecompat/foliotone-archive-7zip/manifests/{MANIFEST_DIGEST}"
CHALLENGE = (
    f'Bearer realm="{REGISTRY_REALM}",service="{REGISTRY_SERVICE}",'
    f'scope="{REGISTRY_SCOPE}"'
)
MAX_CHALLENGE_BYTES = 1_024
MAX_TOKEN_RESPONSE_BYTES = 16_384
MAX_TOKEN_BYTES = 8_192
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
ACTION_IDENTITIES = {
    "actions/attest": "daf44fb950173508f38bd2406030372c1d1162b1",
    "actions/attest-sbom": "4651f806c01d8637787e274ac3bdf724ef169f34",
    "actions/checkout": "11bd71901bbe5b1630ceea73d27597364c9af683",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
}


class EvidenceVerificationError(RuntimeError):
    """A public, path-free supply-chain verification failed closed."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        raise EvidenceVerificationError("registry redirect is forbidden")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_lock() -> dict[str, Any]:
    value = json.loads((PACKAGE_DIR / "archive-image.lock.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("state") != "BOOTSTRAP_LOCKED":
        raise EvidenceVerificationError("locked archive image identity required")
    return value


def build_provenance_predicate(repository_commit: str) -> dict[str, Any]:
    """Build the exact deterministic SLSA-v1 predicate for one final commit."""

    if COMMIT_RE.fullmatch(repository_commit) is None:
        raise EvidenceVerificationError("repository commit must be lowercase SHA-1")
    lock = _load_lock()
    if lock.get("runtime_platform_manifest_digest") != MANIFEST_DIGEST:
        raise EvidenceVerificationError("runtime manifest identity mismatch")
    lock_digest = _sha256(PACKAGE_DIR / "archive-image.lock.json")
    sbom_digest = _sha256(PACKAGE_DIR / "archive-image.spdx.json")
    if sbom_digest != lock.get("sbom_sha256"):
        raise EvidenceVerificationError("SBOM identity mismatch")
    dependencies = [
        {
            "uri": "git+https://github.com/gecompat/FolioTone@refs/heads/main",
            "digest": {"gitCommit": repository_commit},
        },
        {"uri": lock["upstream_url"], "digest": {"sha256": lock["upstream_sha256"]}},
        {"uri": lock["source_tar_url"], "digest": {"sha256": lock["source_tar_sha256"]}},
        {
            "uri": lock["source_copying_url"],
            "digest": {"sha256": lock["source_copying_sha256"]},
        },
        {
            "uri": lock["source_unrar_license_url"],
            "digest": {"sha256": lock["source_unrar_license_sha256"]},
        },
        {
            "uri": lock["buildx_linux_amd64_asset_url"],
            "digest": {"sha256": lock["buildx_linux_amd64_asset_sha256"]},
        },
        {
            "uri": "oci://moby/buildkit",
            "digest": {
                "sha256": lock["buildkit_image_index_digest"].removeprefix("sha256:")
            },
        },
    ]
    action_dependencies = [
        {
            "uri": f"git+https://github.com/{name}",
            "digest": {"gitCommit": commit},
        }
        for name, commit in sorted(ACTION_IDENTITIES.items())
    ]
    byproducts = [
        {
            "uri": f"oci://{IMAGE_NAME}",
            "digest": {
                "sha256": lock["runtime_platform_manifest_digest"].removeprefix("sha256:")
            },
            "annotations": {
                "mediaType": MANIFEST_MEDIA_TYPE,
                "size": lock["runtime_platform_manifest_size_bytes"],
            },
        },
        {
            "uri": "oci-config",
            "digest": {"sha256": lock["runtime_config_digest"].removeprefix("sha256:")},
            "annotations": {"size": lock["runtime_config_size_bytes"]},
        },
        {
            "uri": "oci-layer:rootfs",
            "digest": {
                "sha256": lock["runtime_rootfs_layer_digest"].removeprefix("sha256:"),
            },
            "annotations": {
                "diffId": lock["runtime_rootfs_diff_id"],
                "size": lock["runtime_rootfs_layer_size_bytes"],
                "order": 1,
            },
        },
        {
            "uri": "oci-layer:workdir",
            "digest": {
                "sha256": lock["runtime_workdir_layer_digest"].removeprefix("sha256:"),
            },
            "annotations": {
                "diffId": lock["runtime_workdir_diff_id"],
                "size": lock["runtime_workdir_layer_size_bytes"],
                "order": 2,
            },
        },
        {
            "uri": "archive-image.spdx.json",
            "digest": {"sha256": sbom_digest},
        },
    ]
    return {
        "buildDefinition": {
            "buildType": GITHUB_WORKFLOW_BUILD_TYPE,
            "externalParameters": {
                "workflow": {
                    "ref": "refs/heads/main",
                    "repository": "https://github.com/gecompat/FolioTone",
                    "path": ".github/workflows/archive-image.yml",
                },
            },
            "internalParameters": {
                "github": {
                    "event_name": "push",
                    "repository_id": GITHUB_REPOSITORY_ID,
                    "repository_owner_id": GITHUB_REPOSITORY_OWNER_ID,
                    "runner_environment": "github-hosted",
                },
                "actionIdentities": ACTION_IDENTITIES,
                "archiveImage": {
                    "platform": lock["platform"],
                    "recipeProfile": lock["recipe_profile"],
                    "repositoryCommit": repository_commit,
                    "sourceDateEpoch": lock["source_date_epoch"],
                },
                "base": {
                    "kind": lock["base_kind"],
                    "reference": lock["base_reference"],
                    "digest": lock["base_digest"],
                },
                "buildNetwork": lock["build_network"],
                "buildNoCache": lock["build_no_cache"],
                "buildOutput": lock["build_output"],
                "buildProfile": lock["build_profile"],
                "builderInputs": {
                    "buildkitImageIndexDigest": lock["buildkit_image_index_digest"],
                    "buildkitLinuxAmd64ManifestDigest": lock[
                        "buildkit_linux_amd64_manifest_digest"
                    ],
                    "buildxAssetSize": lock["buildx_linux_amd64_asset_size_bytes"],
                    "buildxAssetSha256": lock["buildx_linux_amd64_asset_sha256"],
                },
                "dockerfileSha256": lock["dockerfile_sha256"],
                "executable": {
                    "name": lock["executable_member_name"],
                    "size": lock["executable_member_size_bytes"],
                    "sha256": lock["executable_member_sha256"],
                },
                "licenseIdentities": {
                    "binaryLicenseSha256": lock["binary_tar_license_sha256"],
                    "binaryReadmeSha256": lock["binary_tar_readme_sha256"],
                    "copyingSha256": lock["source_copying_sha256"],
                    "unrarLicenseSha256": lock["source_unrar_license_sha256"],
                },
                "lockSha256": lock_digest,
                "rootfsTarSha256": lock["rootfs_tar_sha256"],
                "sbomSha256": sbom_digest,
            },
            "resolvedDependencies": dependencies,
        },
        "runDetails": {
            "builder": {
                "id": GITHUB_WORKFLOW_BUILDER_ID,
                "builderDependencies": action_dependencies,
                "version": {
                    "buildkit": lock["buildkit_version"],
                    "buildx": lock["buildx_version"],
                },
            },
            "metadata": {},
            "byproducts": byproducts,
        },
    }


def write_provenance(repository_commit: str, output: Path) -> None:
    predicate = build_provenance_predicate(repository_commit)
    payload = json.dumps(predicate, indent=2, sort_keys=True) + "\n"
    output.write_text(payload, encoding="utf-8", newline="\n")


def verify_attestation_result(
    result_path: Path,
    predicate_path: Path,
    repository_commit: str,
) -> None:
    if result_path.stat().st_size > 4_194_304:
        raise EvidenceVerificationError("attestation verification output exceeds bound")
    if predicate_path.stat().st_size > 1_048_576:
        raise EvidenceVerificationError("provenance predicate exceeds bound")
    expected = json.loads(predicate_path.read_text(encoding="utf-8"))
    if expected != build_provenance_predicate(repository_commit):
        raise EvidenceVerificationError("local provenance predicate is not exact")
    _verify_attestation_results(result_path, PREDICATE_TYPE, expected)


def verify_sbom_attestation_result(result_path: Path) -> None:
    sbom_path = PACKAGE_DIR / "archive-image.spdx.json"
    if sbom_path.stat().st_size > 1_048_576:
        raise EvidenceVerificationError("SPDX predicate exceeds bound")
    expected = json.loads(sbom_path.read_text(encoding="utf-8"))
    _verify_attestation_results(result_path, "https://spdx.dev/Document/v2.3", expected)


def _verify_attestation_results(
    result_path: Path,
    predicate_type: str,
    expected_predicate: object,
) -> None:
    if result_path.stat().st_size > 4_194_304:
        raise EvidenceVerificationError("attestation verification output exceeds bound")
    results = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(results, list) or not results:
        raise EvidenceVerificationError("at least one verified attestation required")
    expected_subject = [
        {
            "name": IMAGE_NAME,
            "digest": {"sha256": MANIFEST_DIGEST.removeprefix("sha256:")},
        }
    ]
    for result in results:
        if not isinstance(result, dict):
            raise EvidenceVerificationError("attestation verification result schema invalid")
        verification = result.get("verificationResult")
        statement = verification.get("statement") if isinstance(verification, dict) else None
        if (
            not isinstance(statement, dict)
            or statement.get("predicateType") != predicate_type
            or statement.get("subject") != expected_subject
            or statement.get("predicate") != expected_predicate
        ):
            raise EvidenceVerificationError("verified attestation content mismatch")


def _read_bounded(response: Any, maximum: int, label: str) -> bytes:
    raw_length = response.headers.get("Content-Length")
    if raw_length is not None:
        try:
            length = int(raw_length)
        except ValueError as error:
            raise EvidenceVerificationError(f"{label} Content-Length invalid") from error
        if length < 0 or length > maximum:
            raise EvidenceVerificationError(f"{label} Content-Length exceeds bound")
    payload = response.read(maximum + 1)
    if not isinstance(payload, bytes):
        raise EvidenceVerificationError(f"{label} body type invalid")
    if len(payload) > maximum:
        raise EvidenceVerificationError(f"{label} exceeds bound")
    if raw_length is not None and len(payload) != int(raw_length):
        raise EvidenceVerificationError(f"{label} Content-Length mismatch")
    return payload


def verify_public_manifest(opener: Any | None = None) -> dict[str, object]:
    """Perform the sole credential-free bounded GHCR Bearer flow."""

    client = opener or urllib.request.build_opener(_NoRedirect())
    initial = urllib.request.Request(
        MANIFEST_URL,
        headers={"Accept": MANIFEST_MEDIA_TYPE, "User-Agent": "FolioTone archive-image/v1"},
    )
    try:
        client.open(initial, timeout=30)
    except urllib.error.HTTPError as error:
        try:
            if error.code != 401:
                raise EvidenceVerificationError("registry challenge status mismatch") from error
            _read_bounded(error, MAX_CHALLENGE_BYTES, "registry challenge")
            if error.headers.get("WWW-Authenticate") != CHALLENGE:
                raise EvidenceVerificationError("registry Bearer challenge mismatch") from error
        finally:
            error.close()
    except (OSError, urllib.error.URLError) as error:
        raise EvidenceVerificationError("registry challenge failed") from error
    else:
        raise EvidenceVerificationError("registry must require the exact anonymous challenge")
    query = urllib.parse.urlencode({"service": REGISTRY_SERVICE, "scope": REGISTRY_SCOPE})
    token_request = urllib.request.Request(
        f"{REGISTRY_REALM}?{query}",
        headers={"Accept": "application/json", "User-Agent": "FolioTone archive-image/v1"},
    )
    try:
        with client.open(token_request, timeout=30) as response:
            if response.status != 200:
                raise EvidenceVerificationError("registry token status mismatch")
            token_payload = _read_bounded(
                response, MAX_TOKEN_RESPONSE_BYTES, "registry token response"
            )
    except (OSError, urllib.error.URLError) as error:
        raise EvidenceVerificationError("registry token request failed") from error
    try:
        token_object = json.loads(token_payload)
        token = token_object["token"]
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceVerificationError("registry token response schema invalid") from error
    if (
        not isinstance(token_object, dict)
        or set(token_object) != {"token"}
        or not isinstance(token, str)
        or not token
        or len(token.encode("utf-8")) > MAX_TOKEN_BYTES
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in token)
    ):
        raise EvidenceVerificationError("registry token is invalid")
    manifest_request = urllib.request.Request(
        MANIFEST_URL,
        headers={
            "Accept": MANIFEST_MEDIA_TYPE,
            "Authorization": f"Bearer {token}",
            "User-Agent": "FolioTone archive-image/v1",
        },
    )
    token_object.clear()
    token_payload = b""
    token = ""
    try:
        with client.open(manifest_request, timeout=30) as response:
            if response.status != 200:
                raise EvidenceVerificationError("registry manifest status mismatch")
            if response.headers.get("Content-Type") != MANIFEST_MEDIA_TYPE:
                raise EvidenceVerificationError("registry manifest media type mismatch")
            if response.headers.get("Docker-Content-Digest") != MANIFEST_DIGEST:
                raise EvidenceVerificationError("registry manifest digest header mismatch")
            if response.headers.get("Content-Length") != str(MANIFEST_SIZE):
                raise EvidenceVerificationError("registry manifest size header mismatch")
            body = _read_bounded(response, MANIFEST_SIZE, "registry manifest")
    except (OSError, urllib.error.URLError) as error:
        raise EvidenceVerificationError("registry manifest request failed") from error
    finally:
        manifest_request.remove_header("Authorization")
    if len(body) != MANIFEST_SIZE:
        raise EvidenceVerificationError("registry manifest descriptor size mismatch")
    if "sha256:" + hashlib.sha256(body).hexdigest() != MANIFEST_DIGEST:
        raise EvidenceVerificationError("registry manifest body digest mismatch")
    return {"profile": "archive-public-manifest-verification/v1", "verified": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    provenance = subparsers.add_parser("provenance")
    provenance.add_argument("--repository-commit", required=True)
    provenance.add_argument("--output", required=True, type=Path)
    attestation = subparsers.add_parser("verify-attestation")
    attestation.add_argument("--repository-commit", required=True)
    attestation.add_argument("--result", required=True, type=Path)
    attestation.add_argument("--predicate", required=True, type=Path)
    sbom_attestation = subparsers.add_parser("verify-sbom-attestation")
    sbom_attestation.add_argument("--result", required=True, type=Path)
    subparsers.add_parser("verify-registry")
    arguments = parser.parse_args()
    try:
        if arguments.command == "provenance":
            write_provenance(arguments.repository_commit, arguments.output)
        elif arguments.command == "verify-attestation":
            verify_attestation_result(
                arguments.result,
                arguments.predicate,
                arguments.repository_commit,
            )
        elif arguments.command == "verify-sbom-attestation":
            verify_sbom_attestation_result(arguments.result)
        else:
            print(json.dumps(verify_public_manifest(), sort_keys=True))
        return 0
    except (EvidenceVerificationError, OSError, UnicodeError, json.JSONDecodeError):
        print("archive supply-chain evidence verification failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
