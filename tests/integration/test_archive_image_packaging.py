from __future__ import annotations

import gzip
import hashlib
import importlib.util
import inspect
import io
import json
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest


def _load_supply_chain_module(name: str) -> ModuleType:
    root = Path(__file__).parents[2] / "packaging" / "archive" / "7zip-26.02"
    spec = importlib.util.spec_from_file_location(name, root / "supply_chain_evidence.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checked_in_archive_image_recipe_has_exact_public_supply_chain_contracts() -> None:
    repository = Path(__file__).parents[2]
    root = repository / "packaging" / "archive" / "7zip-26.02"
    assert (root / "Dockerfile").read_text(encoding="utf-8") == (
        "FROM scratch\n"
        "ADD rootfs.tar /\n"
        "LABEL org.opencontainers.image.source=\"https://github.com/gecompat/FolioTone\"\n"
        "USER 65532:65532\nWORKDIR /workspace\nENTRYPOINT [\"/usr/local/bin/7zzs\"]\n"
    )
    lock = json.loads((root / "archive-image.lock.json").read_text(encoding="utf-8"))
    assert lock["profile"] == "archive-image-lock/v1"
    assert lock["state"] == "BOOTSTRAP_LOCKED"
    assert lock["runtime_platform_manifest_digest"] == (
        "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
    )
    sbom = json.loads((root / "archive-image.spdx.json").read_text(encoding="utf-8"))
    assert sbom["spdxVersion"] == "SPDX-2.3"
    expected = {
        "License.txt": "1790374e5352329cedb46ee3808930a88e9ca2f08b82b10fcf5cf605d2c301b1",
        "copying.txt": "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551",
        "unRarLicense.txt": "17bd9fa4399092c777536fff045b41df76ec9d2ac4c9b8e7345d3b8b6ccc7976",
        "readme.txt": "c3ecf1b8f38631d6ef8a35048e80da77b31cf292a42b3e8793afd44bf4f001b0",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((root / "licenses" / name).read_bytes()).hexdigest() == digest
    subprocess.run(
        [sys.executable, str(root / "validate_supply_chain.py")],
        check=True,
        capture_output=True,
        text=True,
    )
    workflow = (repository / ".github" / "workflows" / "archive-image.yml").read_text(
        encoding="utf-8"
    )
    for scoped_path in (
        "packaging/archive/7zip-26.02/**",
        "src/foliotone/archive/sevenzip.py",
        "src/foliotone/core/enums.py",
        "tests/unit/test_archive_sevenzip.py",
        "tests/integration/test_archive_image_packaging.py",
    ):
        assert workflow.count(scoped_path) == 2
    assert workflow.count("docker buildx build --builder") == 4
    assert workflow.count("type=docker,dest=${RUNNER_TEMP}/archive-measurement.docker.tar") == 1
    assert workflow.count("--platform linux/amd64 --network none --no-cache") == 4
    assert workflow.count("--provenance=false --sbom=false") == 4
    pinned_actions = {
        "actions/attest@daf44fb950173508f38bd2406030372c1d1162b1": 1,
        "actions/attest-sbom@4651f806c01d8637787e274ac3bdf724ef169f34": 1,
        "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683": 3,
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065": 2,
    }
    for action, count in pinned_actions.items():
        assert workflow.count(action) == count
    assert "actions/attest-build-provenance@" not in workflow
    assert "published_public_source_associated" not in workflow
    assert "BOOTSTRAP_LOCKED" in workflow
    assert "supply_chain_evidence.py verify-attestation" in workflow
    assert "supply_chain_evidence.py verify-registry" in workflow
    assert "verify-sbom-attestation" in workflow
    assert workflow.count("verify-release --cryptographic") == 1
    assert workflow.count("supply_chain_evidence.py verify-release") == 1
    assert workflow.count("verify-offline-release --artifact") == 1
    assert workflow.count("--bundle-from-oci") == 2
    assert workflow.count("Prepare minimal GHCR credentials for attestation actions") == 1
    assert workflow.count(
        'docker --config "$HOME/.docker" login ghcr.io'
    ) == 1
    assert workflow.count('docker --config "$HOME/.docker" logout ghcr.io') == 1
    assert "env -i PATH=/usr/bin:/bin" in workflow
    assert "curl " not in workflow
    assert "/users/gecompat/packages/container/foliotone-archive-7zip" in workflow
    assert "/orgs/gecompat/packages/" not in workflow


def test_provision_cli_delegates_all_authority_to_the_single_complete_entry() -> None:
    module = _load_supply_chain_module("foliotone_test_provision_delegation")
    source = inspect.getsource(module.provision_runtime)
    assert "provision_archive_7zip_runtime" in source
    assert "verify_public_manifest" not in source
    assert "verify_public_source_association" not in source
    assert "verify_checked_in_release" not in source
    parameters = inspect.signature(module.provision_runtime).parameters
    assert "artifact" in parameters
    assert "release_path" not in parameters
    assert "revocations_path" not in parameters
    assert "evidence_directory" not in parameters


def test_custom_provenance_is_deterministic_and_verified_exactly(tmp_path: Path) -> None:
    root = Path(__file__).parents[2] / "packaging" / "archive" / "7zip-26.02"
    script = root / "supply_chain_evidence.py"
    spec = importlib.util.spec_from_file_location("foliotone_test_supply_evidence", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    commit = "a" * 40
    invocation_id = (
        "https://github.com/gecompat/FolioTone/actions/runs/123456789/attempts/1"
    )
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    module.write_provenance(commit, invocation_id, first)
    module.write_provenance(commit, invocation_id, second)
    assert first.read_bytes() == second.read_bytes()
    predicate = json.loads(first.read_text(encoding="utf-8"))
    assert predicate == module.build_provenance_predicate(commit, invocation_id)
    assert predicate["runDetails"]["metadata"] == {"invocationId": invocation_id}
    assert predicate["buildDefinition"]["buildType"] == (
        "https://actions.github.io/buildtypes/workflow/v1"
    )
    assert predicate["buildDefinition"]["externalParameters"] == {
        "workflow": {
            "ref": "refs/heads/main",
            "repository": "https://github.com/gecompat/FolioTone",
            "path": ".github/workflows/archive-image.yml",
        }
    }
    assert predicate["buildDefinition"]["resolvedDependencies"][0] == {
        "uri": "git+https://github.com/gecompat/FolioTone@refs/heads/main",
        "digest": {"gitCommit": commit},
    }
    assert predicate["buildDefinition"]["internalParameters"]["archiveImage"] == {
        "platform": "linux/amd64",
        "recipeProfile": "archive-7zip-image/v1",
        "repositoryCommit": commit,
        "sourceDateEpoch": 1782345600,
    }
    assert predicate["buildDefinition"]["internalParameters"]["github"] == {
        "event_name": "push",
        "repository_id": "1328118830",
        "repository_owner_id": "48807214",
        "runner_environment": "github-hosted",
    }
    assert predicate["buildDefinition"]["internalParameters"]["actionIdentities"] == (
        module.ACTION_IDENTITIES
    )
    assert predicate["runDetails"]["builder"]["id"] == (
        "https://github.com/gecompat/FolioTone/.github/workflows/"
        "archive-image.yml@refs/heads/main"
    )
    with pytest.raises(module.EvidenceVerificationError, match="invocation identity"):
        module.build_provenance_predicate(
            commit,
            "https://github.com/other/project/actions/runs/1/attempts/1",
        )
    result = tmp_path / "verified.json"
    entry = {
        "verificationResult": {
            "statement": {
                "subject": [{
                    "name": module.IMAGE_NAME,
                    "digest": {"sha256": module.MANIFEST_DIGEST[7:]},
                }],
                "predicateType": module.PREDICATE_TYPE,
                "predicate": predicate,
            }
        }
    }
    result.write_text(json.dumps([entry]), encoding="utf-8")
    module.verify_attestation_result(result, first, commit, invocation_id)
    result.write_text("[]", encoding="utf-8")
    with pytest.raises(module.EvidenceVerificationError, match="exactly one"):
        module.verify_attestation_result(result, first, commit, invocation_id)
    result.write_text(json.dumps([entry, entry]), encoding="utf-8")
    with pytest.raises(module.EvidenceVerificationError, match="exactly one"):
        module.verify_attestation_result(result, first, commit, invocation_id)
    mismatched = json.loads(json.dumps(entry))
    mismatched["verificationResult"]["statement"]["predicateType"] = "wrong"
    result.write_text(json.dumps([mismatched]), encoding="utf-8")
    with pytest.raises(module.EvidenceVerificationError, match="content mismatch"):
        module.verify_attestation_result(result, first, commit, invocation_id)
    sbom = json.loads((root / "archive-image.spdx.json").read_text(encoding="utf-8"))
    sbom_entry = json.loads(json.dumps(entry))
    statement = sbom_entry["verificationResult"]["statement"]
    statement["predicateType"] = "https://spdx.dev/Document/v2.3"
    statement["predicate"] = sbom
    result.write_text(json.dumps([sbom_entry]), encoding="utf-8")
    module.verify_sbom_attestation_result(result)
    bad_sbom = json.loads(json.dumps(sbom_entry))
    bad_sbom["verificationResult"]["statement"]["predicate"]["name"] = "wrong"
    result.write_text(json.dumps([bad_sbom]), encoding="utf-8")
    with pytest.raises(module.EvidenceVerificationError, match="content mismatch"):
        module.verify_sbom_attestation_result(result)


def test_registry_verifier_uses_only_exact_bounded_bearer_flow() -> None:
    root = Path(__file__).parents[2] / "packaging" / "archive" / "7zip-26.02"
    script = root / "supply_chain_evidence.py"
    spec = importlib.util.spec_from_file_location("foliotone_test_registry_evidence", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    lock = module._load_lock()
    manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": module.MANIFEST_MEDIA_TYPE,
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": lock["runtime_config_digest"],
                "size": lock["runtime_config_size_bytes"],
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": lock["runtime_rootfs_layer_digest"],
                    "size": lock["runtime_rootfs_layer_size_bytes"],
                    "annotations": {
                        "buildkit/rewritten-timestamp": "1782345600"
                    },
                },
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": lock["runtime_workdir_layer_digest"],
                    "size": lock["runtime_workdir_layer_size_bytes"],
                    "annotations": {
                        "buildkit/rewritten-timestamp": "1782345600"
                    },
                },
            ],
        },
        separators=(",", ":"),
    ).encode()
    module.MANIFEST_SIZE = len(manifest)
    module.MANIFEST_DIGEST = "sha256:" + hashlib.sha256(manifest).hexdigest()
    module.MANIFEST_URL = (
        "https://ghcr.io/v2/gecompat/foliotone-archive-7zip/manifests/"
        + module.MANIFEST_DIGEST
    )

    class Response(io.BytesIO):
        def __init__(self, payload: bytes, headers: dict[str, str]) -> None:
            super().__init__(payload)
            self.status = 200
            self.headers = headers

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

    class Opener:
        def __init__(
            self,
            challenge: str = module.CHALLENGE,
            *,
            token_body: bytes = b'{"token":"ephemeral"}',
            manifest_headers: dict[str, str] | None = None,
        ) -> None:
            self.requests: list[urllib.request.Request] = []
            self.challenge = challenge
            self.token_body = token_body
            self.manifest_headers = manifest_headers

        def open(self, request: urllib.request.Request, *, timeout: int) -> Response:
            assert timeout == 30
            self.requests.append(request)
            if len(self.requests) == 1:
                challenge_body = b'{"errors":[]}'
                raise urllib.error.HTTPError(
                    request.full_url,
                    401,
                    "Unauthorized",
                    {
                        "Content-Length": str(len(challenge_body)),
                        "WWW-Authenticate": self.challenge,
                    },
                    io.BytesIO(challenge_body),
                )
            if len(self.requests) == 2:
                return Response(
                    self.token_body,
                    {"Content-Length": str(len(self.token_body))},
                )
            assert request.get_header("Authorization") == "Bearer ephemeral"
            return Response(
                manifest,
                self.manifest_headers or {
                    "Content-Type": module.MANIFEST_MEDIA_TYPE,
                    "Content-Length": str(len(manifest)),
                    "Docker-Content-Digest": module.MANIFEST_DIGEST,
                },
            )

    opener = Opener()
    assert module.verify_public_manifest(opener) == {
        "profile": "archive-public-manifest-verification/v1",
        "verified": True,
    }
    assert len(opener.requests) == 3
    assert opener.requests[0].get_header("Authorization") is None
    assert opener.requests[1].get_header("Authorization") is None
    assert opener.requests[2].get_header("Authorization") is None
    with pytest.raises(module.EvidenceVerificationError, match="challenge"):
        module.verify_public_manifest(Opener('Bearer realm="https://example.invalid"'))
    for token in ("line\nfeed", "carriage\rreturn", "control\u0001", "x" * 8_193):
        token_body = json.dumps({"token": token}, separators=(",", ":")).encode()
        with pytest.raises(module.EvidenceVerificationError, match="token is invalid"):
            module.verify_public_manifest(Opener(token_body=token_body))
    failing_manifest = Opener(
        manifest_headers={
            "Content-Type": module.MANIFEST_MEDIA_TYPE,
            "Content-Length": str(len(manifest)),
            "Docker-Content-Digest": "sha256:" + "0" * 64,
        }
    )
    with pytest.raises(module.EvidenceVerificationError, match="digest header"):
        module.verify_public_manifest(failing_manifest)
    assert failing_manifest.requests[2].get_header("Authorization") is None
    with pytest.raises(module.EvidenceVerificationError, match="redirect"):
        module._NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.invalid")


@pytest.mark.parametrize(
    ("label", "maximum_name"),
    [
        ("registry challenge", "MAX_CHALLENGE_BYTES"),
        ("registry token", "MAX_TOKEN_RESPONSE_BYTES"),
        ("registry manifest", "MANIFEST_SIZE"),
    ],
)
def test_registry_response_content_lengths_fail_closed(
    label: str,
    maximum_name: str,
) -> None:
    root = Path(__file__).parents[2] / "packaging" / "archive" / "7zip-26.02"
    script = root / "supply_chain_evidence.py"
    spec = importlib.util.spec_from_file_location("foliotone_test_registry_lengths", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    maximum = getattr(module, maximum_name)

    class Response(io.BytesIO):
        def __init__(self, content_length: str) -> None:
            super().__init__(b"abc")
            self.headers = {"Content-Length": content_length}

    for content_length in ("invalid", "-1", str(maximum + 1), "1"):
        with pytest.raises(module.EvidenceVerificationError, match="Content-Length"):
            module._read_bounded(Response(content_length), maximum, label)


@pytest.mark.parametrize(
    ("label", "maximum_name"),
    [
        ("registry challenge", "MAX_CHALLENGE_BYTES"),
        ("registry token", "MAX_TOKEN_RESPONSE_BYTES"),
        ("registry manifest", "MANIFEST_SIZE"),
    ],
)
def test_registry_response_body_overflow_without_content_length(
    label: str,
    maximum_name: str,
) -> None:
    root = Path(__file__).parents[2] / "packaging" / "archive" / "7zip-26.02"
    script = root / "supply_chain_evidence.py"
    spec = importlib.util.spec_from_file_location("foliotone_test_registry_overflow", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    maximum = getattr(module, maximum_name)

    class Response(io.BytesIO):
        def __init__(self) -> None:
            super().__init__(b"x" * (maximum + 1))
            self.headers: dict[str, str] = {}

    with pytest.raises(module.EvidenceVerificationError, match="exceeds bound"):
        module._read_bounded(Response(), maximum, label)


def test_oci_inspector_accepts_only_one_hash_verified_linux_amd64_manifest(
    tmp_path: Path,
) -> None:
    root = Path(__file__).parents[2] / "packaging" / "archive" / "7zip-26.02"
    script = root / "inspect_oci_layout.py"
    spec = importlib.util.spec_from_file_location("foliotone_test_oci_inspector", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    synthetic_files = {
        "usr/local/bin/7zzs": b"synthetic-static-elf",
        "usr/share/licenses/7zip/License.txt": b"synthetic-license",
    }
    module.ROOTFS_FILES = {
        name: (
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            0o555 if name.endswith("7zzs") else 0o444,
        )
        for name, payload in synthetic_files.items()
    }

    def write_layout(path: Path, *, user: str) -> object:
        directories = {"workspace", "workspace/input", "workspace/output"}
        for name in synthetic_files:
            parent = Path(name).parent
            while str(parent) != ".":
                directories.add(parent.as_posix())
                parent = parent.parent
        layer_buffer = io.BytesIO()
        with tarfile.open(fileobj=layer_buffer, mode="w") as layer:
            entries = [(name, None) for name in directories] + list(synthetic_files.items())
            for name, payload in sorted(entries):
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE if payload is None else tarfile.REGTYPE
                info.size = 0 if payload is None else len(payload)
                info.mode = 0o555 if payload is None or name.endswith("7zzs") else 0o444
                info.mtime = module.SOURCE_DATE_EPOCH
                layer.addfile(info, None if payload is None else io.BytesIO(payload))
        uncompressed = layer_buffer.getvalue()
        diff_id = "sha256:" + hashlib.sha256(uncompressed).hexdigest()
        compressed = gzip.compress(uncompressed, mtime=0)
        layer_digest = "sha256:" + hashlib.sha256(compressed).hexdigest()
        empty_layer = gzip.compress(bytes(1_024), mtime=0)
        empty_diff_id = "sha256:" + hashlib.sha256(bytes(1_024)).hexdigest()
        empty_layer_digest = "sha256:" + hashlib.sha256(empty_layer).hexdigest()
        config = json.dumps(
            {
                "architecture": "amd64",
                "os": "linux",
                "created": module.SOURCE_CREATED,
                "config": {
                    "User": user,
                    "Env": [module.BUILDKIT_PATH],
                    "Entrypoint": ["/usr/local/bin/7zzs"],
                    "WorkingDir": "/workspace",
                    "Labels": {"org.opencontainers.image.source": module.SOURCE_LABEL},
                },
                "rootfs": {"type": "layers", "diff_ids": [diff_id, empty_diff_id]},
                "history": [
                    {
                        "created": module.SOURCE_CREATED,
                        "created_by": "ADD rootfs.tar / # buildkit",
                        "comment": "buildkit.dockerfile.v0",
                    },
                    {
                        "created": module.SOURCE_CREATED,
                        "created_by": (
                            "LABEL org.opencontainers.image.source="
                            "https://github.com/gecompat/FolioTone"
                        ),
                        "comment": "buildkit.dockerfile.v0",
                        "empty_layer": True,
                    },
                    {
                        "created": module.SOURCE_CREATED,
                        "created_by": "USER 65532:65532",
                        "comment": "buildkit.dockerfile.v0",
                        "empty_layer": True,
                    },
                    {
                        "created": module.SOURCE_CREATED,
                        "created_by": "WORKDIR /workspace",
                        "comment": "buildkit.dockerfile.v0",
                    },
                    {
                        "created": module.SOURCE_CREATED,
                        "created_by": 'ENTRYPOINT ["/usr/local/bin/7zzs"]',
                        "comment": "buildkit.dockerfile.v0",
                        "empty_layer": True,
                    },
                ],
            },
            separators=(",", ":"),
        ).encode()
        config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
        manifest = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": module.OCI_MANIFEST,
                "config": {
                    "mediaType": module.OCI_CONFIG,
                    "digest": config_digest,
                    "size": len(config),
                },
                "layers": [
                    {
                        "mediaType": module.OCI_GZIP_LAYER,
                        "digest": layer_digest,
                        "size": len(compressed),
                        "annotations": module.REWRITTEN_TIMESTAMP_ANNOTATION,
                    },
                    {
                        "mediaType": module.OCI_GZIP_LAYER,
                        "digest": empty_layer_digest,
                        "size": len(empty_layer),
                        "annotations": module.REWRITTEN_TIMESTAMP_ANNOTATION,
                    },
                ],
            },
            separators=(",", ":"),
        ).encode()
        manifest_digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
        index = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": module.OCI_INDEX,
                "manifests": [{
                    "mediaType": module.OCI_MANIFEST,
                    "digest": manifest_digest,
                    "size": len(manifest),
                    "annotations": {
                        "org.opencontainers.image.created": module.SOURCE_CREATED
                    },
                    "platform": {"architecture": "amd64", "os": "linux"},
                }],
            },
            separators=(",", ":"),
        ).encode()
        blobs = {
            manifest_digest: manifest,
            config_digest: config,
            layer_digest: compressed,
            empty_layer_digest: empty_layer,
        }
        with tarfile.open(path, "w") as archive:
            payloads = [("oci-layout", b'{"imageLayoutVersion":"1.0.0"}'), ("index.json", index)]
            payloads.extend(
                (f"blobs/sha256/{digest[7:]}", payload)
                for digest, payload in blobs.items()
            )
            for name, payload in payloads:
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        return module.OciIdentity(
            manifest_digest,
            len(manifest),
            config_digest,
            len(config),
            layer_digest,
            len(compressed),
            diff_id,
            empty_layer_digest,
            len(empty_layer),
            empty_diff_id,
        )

    valid = tmp_path / "valid.oci.tar"
    expected_identity = write_layout(valid, user="65532:65532")
    module.EXPECTED_OCI_IDENTITY = expected_identity
    assert module.inspect_oci_layout(valid) == expected_identity
    invalid = tmp_path / "wrong-user.oci.tar"
    write_layout(invalid, user="0:0")
    try:
        module.inspect_oci_layout(invalid)
    except ValueError as error:
        assert str(error) == "OCI runtime user mismatch"
    else:
        raise AssertionError("wrong runtime user must fail closed")


def test_supply_chain_downloads_are_bounded_and_remove_partial_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).parents[2] / "packaging" / "archive" / "7zip-26.02"
    script = root / "prepare_archive_image.py"
    spec = importlib.util.spec_from_file_location("foliotone_test_archive_prepare", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class Response(io.BytesIO):
        def __init__(self, payload: bytes, content_length: str | None) -> None:
            super().__init__(payload)
            self.headers = {} if content_length is None else {"Content-Length": content_length}

    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(b"abcd", "4"),
    )
    with pytest.raises(module.VerificationError, match="Content-Length"):
        module.acquire(tmp_path, "bounded.bin", "https://example.invalid/fixed", 3, "0" * 64)
    assert not (tmp_path / ".bounded.bin.partial").exists()
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(b"abcd", None),
    )
    with pytest.raises(module.VerificationError, match="exceeded"):
        module.acquire(tmp_path, "capped.bin", "https://example.invalid/fixed", 3, "0" * 64)
    assert not (tmp_path / ".capped.bin.partial").exists()


def test_duplicate_normalized_upstream_tar_members_fail_closed(tmp_path: Path) -> None:
    root = Path(__file__).parents[2] / "packaging" / "archive" / "7zip-26.02"
    script = root / "prepare_archive_image.py"
    spec = importlib.util.spec_from_file_location(
        "foliotone_test_archive_prepare_duplicate", script
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    archive_path = tmp_path / "duplicate.tar.xz"
    with tarfile.open(archive_path, "w:xz") as archive:
        for _ in range(2):
            info = tarfile.TarInfo("7zzs")
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
    destination = tmp_path / "output"
    with pytest.raises(module.VerificationError, match="duplicate normalized"):
        module.extract_binary_members(archive_path, destination)
