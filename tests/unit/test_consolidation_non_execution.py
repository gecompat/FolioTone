"""Static non-execution gates for the W9 consolidation package.

The scanners intentionally fail closed. They are a regression gate for the
narrow W9 boundary, not a general-purpose Python security analyser.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Iterable
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION_ROOT = REPOSITORY_ROOT / "src" / "foliotone" / "consolidation"
CALIBRE_LIBRARY_FILE = REPOSITORY_ROOT / "src" / "foliotone" / "adapters" / "calibre" / "library.py"

FORBIDDEN_MODULES = frozenset({"os", "pathlib", "shutil", "subprocess", "importlib"})
FORBIDDEN_CALLS = frozenset(
    {
        "os.remove",
        "os.unlink",
        "os.rename",
        "os.replace",
        "shutil.move",
        "shutil.rmtree",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.run",
        "importlib.import_module",
    }
)
DYNAMIC_EXECUTION_REFERENCES = frozenset(
    {
        "__import__",
        "builtins.__import__",
        "builtins.compile",
        "builtins.eval",
        "builtins.exec",
        "compile",
        "eval",
        "exec",
        "importlib.import_module",
    }
)
FORBIDDEN_PATH_METHODS = frozenset(
    {
        "unlink",
        "rmdir",
        "rename",
        "replace",
        "write_bytes",
        "write_text",
        "touch",
        "mkdir",
        "chmod",
        "lchmod",
        "symlink_to",
        "hardlink_to",
    }
)
FORBIDDEN_PUBLIC_SURFACE = re.compile(
    r"^(execute|apply|delete|move|rename|quarantine|purge)(?:_|$)"
)
FORBIDDEN_CALIBRE_SUBCOMMANDS = frozenset(
    {
        "add",
        "add_format",
        "remove",
        "remove_format",
        "set_metadata",
        "embed_metadata",
        "backup_metadata",
        "restore_database",
        "export",
    }
)
ALLOWED_CALIBRE_SUBCOMMANDS = frozenset(
    {"--version", "list", "search", "show_metadata", "list_categories"}
)
SHELL_DELETION = re.compile(
    r"(?:^|[;&|]\s*|\bsudo\s+|\b(?:bash|sh)\s+-c\s+|"
    r"\b(?:powershell|pwsh)(?:\.exe)?\s+-(?:command|c)\s+|\bcmd(?:\.exe)?\s+/c\s+)"
    r"(?:rm|del|erase|rmdir|rd|remove-item|unlink)(?:\s|$)",
    re.IGNORECASE,
)
CALIBRE_DESCRIPTOR_KEYWORDS = frozenset(
    {
        "accepted_exit_codes",
        "args",
        "capability",
        "environment",
        "executable",
        "max_stdout_bytes",
        "timeout_seconds",
        "version_policy",
        "workspace_environment",
    }
)
SAFE_PARAMETER_RETURN_SITES = frozenset(
    {
        ("blockers.py", "_blocker", "code"),
        ("blockers.py", "_blocker", "refs"),
        ("blockers.py", "_sorted_evidence", "refs"),
        ("contracts.py", "_id", "value"),
        ("contracts.py", "_normalized_quality_material", "value"),
        ("contracts.py", "_text", "field_name"),
        ("contracts.py", "_text", "value"),
        ("contracts.py", "consolidation_quality_evidence_fingerprint", "encoded"),
        ("contracts.py", "snapshot", "role"),
        ("keep_preference.py", "_candidate_set_fingerprint", "configuration_fingerprint"),
        ("keep_preference.py", "_digest", "value"),
        ("keep_preference.py", "_evidence_fingerprint", "candidate_set_fingerprint"),
        ("keep_preference.py", "_evidence_fingerprint", "configuration_fingerprint"),
        ("keep_preference.py", "_evidence_fingerprint", "hard_constraint_material"),
        ("keep_preference.py", "_id", "value"),
        ("keep_preference.py", "build_keep_preference", "candidate_set_fingerprint"),
        ("keep_preference.py", "build_keep_preference", "config_fingerprint"),
        ("keep_preference.py", "build_keep_preference", "evidence_fingerprint"),
        ("keep_preference.py", "build_keep_preference", "quality_evidence"),
        ("planner.py", "_blocker", "code"),
        ("planner.py", "_blocker", "refs"),
        ("planner.py", "_candidate_snapshot", "candidate_set_fingerprint"),
        ("planner.py", "_candidate_snapshot", "created_at"),
        ("planner.py", "_candidate_snapshot", "dependency_fingerprint"),
        ("planner.py", "_candidate_snapshot", "evidence_fingerprint"),
        ("planner.py", "_candidate_snapshot", "intents"),
        ("planner.py", "_candidate_snapshot", "precondition_fingerprint"),
        ("planner.py", "_canonicalize", "value"),
        ("planner.py", "_digest", "value"),
        ("planner.py", "_ephemeral_review_approval", "fallback_id"),
        ("planner.py", "_ephemeral_review_approval", "review_type"),
        (
            "planner.py",
            "consolidation_candidate_material_fingerprints",
            "candidate_set_fingerprint",
        ),
        ("planner.py", "consolidation_candidate_material_fingerprints", "dependency_fingerprint"),
        ("planner.py", "consolidation_candidate_material_fingerprints", "evidence_fingerprint"),
        ("planner.py", "consolidation_candidate_material_fingerprints", "precondition_fingerprint"),
        ("planner.py", "snapshot", "code"),
        ("serialization.py", "_normalize", "value"),
        ("serialization.py", "_sorted_unique", "ordered"),
        ("serialization.py", "_timestamp", "value"),
        ("serialization.py", "canonical_consolidation_plan_payload", "plan"),
        ("serialization.py", "consolidation_plan_content_hash", "plan"),
        ("serialization.py", "serialize_consolidation_plan", "normalized"),
        ("library.py", "_normalize_format_locator", "relative"),
        ("library.py", "_parse_optional_text", "value"),
        ("library.py", "_parse_record", "raw_record"),
        ("library.py", "_parse_record", "record_id"),
        ("library.py", "_parse_record_id", "value"),
        ("library.py", "_validated_library_path", "value"),
        ("library.py", "_validated_page_size", "limit"),
        ("library.py", "_validated_record_id", "record_id"),
        ("library.py", "build_calibredb_exact_id_command", "path"),
        ("library.py", "build_calibredb_inventory_command", "page_size"),
        ("library.py", "build_calibredb_inventory_command", "path"),
        ("library.py", "build_calibredb_list_categories_command", "path"),
        ("library.py", "build_calibredb_show_metadata_command", "exact_id"),
        ("library.py", "build_calibredb_show_metadata_command", "path"),
    }
)
SAFE_PARAMETER_RETURN_FUNCTION_DIGESTS = {
    (
        "blockers.py",
        "_sorted_evidence",
    ): "8ed88c794446427f50b03e7f8399deb8fd1330ac2cee668e6b7b804413cb5430",
    ("blockers.py", "_blocker"): "edacc536fe5e655eb1cbb3155ec3ac14fe23249b7c80cc1476a6d770b87d7765",
    ("contracts.py", "_id"): "f3535111499a0125cbfc129feaface0746c2e9e1383de912c55380ce97fa6196",
    ("contracts.py", "_text"): "ac40ffaa67b69b832c6c6cdf0dc8c967bbcd54af9f36a8ad16df2796b7553e19",
    (
        "contracts.py",
        "_normalized_quality_material",
    ): "22d6b4a9d9d7919267037bf18a333425ae9cdce738a34d253ee65c91db326092",
    (
        "contracts.py",
        "consolidation_quality_evidence_fingerprint",
    ): "fed4c329fc1a199386bb5f2945e08e304bf622c75dd8c2e1bc9b06ba81583e84",
    (
        "contracts.py",
        "snapshot",
    ): "9bd6e7971dbb50da391390c63e14d1780384088986ed268c9be579c63daa7687",
    (
        "keep_preference.py",
        "_digest",
    ): "286c401da4b40df6e027fea203430a70722ba7877a263aaaabed7842424dc0d7",
    (
        "keep_preference.py",
        "_id",
    ): "60d667b4fd0ec504004b73a8a9450a92fe2e76d30f460a0091853756ceeb24d4",
    (
        "keep_preference.py",
        "_candidate_set_fingerprint",
    ): "8a31fbe5878c7c818e65d2d9a793ab928892db95b6c2958d939889586d8c3fe6",
    (
        "keep_preference.py",
        "_evidence_fingerprint",
    ): "16a22285e8cde3b27b40ab660270b658b729630beffe2a76cc276495226af70a",
    (
        "keep_preference.py",
        "build_keep_preference",
    ): "120eab84cdf14a5544cd668937bb385704315599af5f4e3104b1ecb9609cde80",
    (
        "planner.py",
        "_canonicalize",
    ): "ea719f117e29187aca73cea6ac6a71dac7f8d94294a9bd3caefd199b1d4dc777",
    ("planner.py", "_digest"): "cbf2a39973965d327d0e4b823163506a61ebe75660ef9aa87a61cbc2140309e6",
    (
        "planner.py",
        "consolidation_candidate_material_fingerprints",
    ): "563ee948d5b8597a5060cef1b4844bc40a86c7a6e085921fe986921f71b03075",
    (
        "planner.py",
        "_candidate_snapshot",
    ): "c073c7b376efda27b889833db840dbcb0171b6b96243f9b63847ec182c1062d0",
    (
        "planner.py",
        "_ephemeral_review_approval",
    ): "7bb95853dfecf333c7fb75c70c7292b8f29647d638b28612fd82c8c3c63c29d1",
    ("planner.py", "_blocker"): "bf9197e22bd996053e6b41f57a9ce0708d1b9b7c09c625b2d81627075a1f60f9",
    ("planner.py", "snapshot"): "99c0a108afbe3e4d816ef32f7727529763d716e1092ee96e3773945df20a5199",
    (
        "serialization.py",
        "_timestamp",
    ): "cc5002ff476ee7530aab85fd8825344b8683609c30629339cf1274c7e4f81af5",
    (
        "serialization.py",
        "_sorted_unique",
    ): "e29878ec37ad42f6a7ee7722472803e060bfe2ae2fcdd2eb2b7a147d22ebe8a9",
    (
        "serialization.py",
        "_normalize",
    ): "98ffc48fda8413c6739592fcadb6e702923047fddc9213e81e76c4aa49875945",
    (
        "serialization.py",
        "canonical_consolidation_plan_payload",
    ): "e7ccbb60925736babe0da8e2bef6062faed3e8db2f95bff1d903fe553fa0cf5c",
    (
        "serialization.py",
        "serialize_consolidation_plan",
    ): "c7d05a5d77b0d7c344fa73fe5a46200b6fd88b1742ba3f3dbd5d34878fe30c00",
    (
        "serialization.py",
        "consolidation_plan_content_hash",
    ): "8d291916a813dc72d00a9934d2ae9102f3d9db158ab2fbb13ec8f0fc3891f6c3",
    (
        "library.py",
        "_parse_record",
    ): "c60fbf18b376b981a7acfa8474b808822fd9923993fd7b0f80acae28d154afe2",
    (
        "library.py",
        "_parse_record_id",
    ): "cf145ba4b6db000eb73801a0b32e06e3c0d31d802e4dde866edc222121e19800",
    (
        "library.py",
        "_parse_optional_text",
    ): "b5b7b42ec1fcfba44c48261762d24091e20ada7c9478d2f4605e0cc5ca9a73c0",
    (
        "library.py",
        "_normalize_format_locator",
    ): "961cca1ba18e54605d58e353db2d852abd001b766bd618b6e05d20598a88a82e",
    (
        "library.py",
        "build_calibredb_inventory_command",
    ): "5761b41214a44309f349edb8072752d235ecdec92113e222bc95fbf223ffd88a",
    (
        "library.py",
        "build_calibredb_exact_id_command",
    ): "ae2ac1b76311294cc1af09fafd816c01a7c79857f46f9835f5737f341ea4aaf5",
    (
        "library.py",
        "build_calibredb_show_metadata_command",
    ): "daadf524f670378d17bab14d84e56baa417ed937eb0f53c2ac76564285b4c751",
    (
        "library.py",
        "build_calibredb_list_categories_command",
    ): "d2409ceb60318e4ea727cf484fde4b63d75ffee00bc0cb2e9d01307a4633dc4c",
    (
        "library.py",
        "_validated_library_path",
    ): "4bf091f92c39f360033a776bdbfd670c053ab1e12ff63e16d0720068c21d72d9",
    (
        "library.py",
        "_validated_record_id",
    ): "3e0d65438787b0c6e306c8ecb0bf8ed207aab1de6e63381051c6f6d0fb2ac80d",
    (
        "library.py",
        "_validated_page_size",
    ): "36cc7ef6333733a1e027246a632c9138d3c8049fd7e34f55046bb76e3bec7b2f",
}
SAFE_PARAMETER_CALLEES = frozenset(
    {
        "foliotone.consolidation.blockers.ConsolidationHardBlockerInputs",
        "foliotone.consolidation.blockers.build_consolidation_blockers",
        "foliotone.consolidation.contracts.ConsolidationBlocker",
        "foliotone.consolidation.contracts.ConsolidationCandidateSnapshot",
        "foliotone.consolidation.contracts.ConsolidationFilePreconditionSnapshot",
        "foliotone.consolidation.contracts.ConsolidationPlan",
        "foliotone.consolidation.contracts.ConsolidationReviewSnapshot",
        "foliotone.consolidation.contracts.KeepPreferenceOutcome",
        "foliotone.consolidation.serialization.consolidation_plan_content_hash",
        "foliotone.core._validation.require_aware_datetime",
        "foliotone.core._validation.require_non_empty",
        "foliotone.tooling.structured.parse_json_output",
        "hashlib.sha256",
        "json.dumps",
        "pathlib.PurePosixPath",
        "unicodedata.normalize",
    }
)
SAFE_PARAMETER_CALL_SITES = frozenset(
    {
        ("blockers.py", "build_consolidation_blockers", "codes.update", "0"),
        ("keep_preference.py", "build_keep_preference", "preference_ranks.get", "0"),
        ("planner.py", "build_consolidation_plan", "blockers.append", "0"),
        ("library.py", "_parse_text_list", "parsed.append", "0"),
        (
            "preconditions.py",
            "build_consolidation_file_preconditions",
            "preconditions.append",
            "0",
        ),
    }
)
SAFE_PARAMETER_CALL_FUNCTION_DIGESTS = {
    (
        "blockers.py",
        "build_consolidation_blockers",
    ): "6ae4c258a2eaf168d6b594ca02a6ec573a0a7ca9431c343de3ccb68320834465",
    (
        "keep_preference.py",
        "build_keep_preference",
    ): "120eab84cdf14a5544cd668937bb385704315599af5f4e3104b1ecb9609cde80",
    (
        "planner.py",
        "build_consolidation_plan",
    ): "562480e25c0b4e50a78548d34adbe2fea0a980226f6b3449f61492cfbc294c6e",
    (
        "preconditions.py",
        "build_consolidation_file_preconditions",
    ): "084cccd43c61a7177dabd94e379afb683e13d8e8f40ed1745b381f2bf73c3b16",
    (
        "library.py",
        "_parse_text_list",
    ): "788b020b01c0dde7a8e7b4801bef34f2d7eae6c2590ef46602b6e21935db5372",
}
SAFE_NAMESPACE_ASSIGNMENT_DIGESTS = {
    ("contracts.py", "__all__"): "b7a20ee791a42f0ca58f1f18376c4caa777af74fbed4f7c72ce3bc8c557ddc8e"
}


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.rglob("*.py")))


def _qualified_name(node: ast.AST | None, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value, aliases)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _assignment_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (node.attr,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for item in node.elts for name in _assignment_names(item))
    return ()


def _looks_like_public_alias(node: ast.AST) -> bool:
    return isinstance(node, (ast.Attribute, ast.Call, ast.Lambda, ast.Name))


def _public_nodes(tree: ast.Module) -> tuple[ast.AST, ...]:
    nodes: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                nodes.append(node)
            if isinstance(node, ast.ClassDef):
                nodes.extend(
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not child.name.startswith("_")
                )
                nodes.extend(
                    child
                    for child in node.body
                    if isinstance(child, (ast.Assign, ast.AnnAssign))
                    and _looks_like_public_alias(child.value)
                    and any(
                        not name.startswith("_")
                        for target in (
                            child.targets if isinstance(child, ast.Assign) else (child.target,)
                        )
                        for name in _assignment_names(target)
                    )
                )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            if _looks_like_public_alias(node.value) and any(
                not name.startswith("_") for target in targets for name in _assignment_names(target)
            ):
                nodes.append(node)
    return tuple(nodes)


def _parameters(node: ast.AST) -> tuple[str, ...]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ()
    return _parameters_from_arguments(node.args)


def _parameters_from_arguments(arguments: ast.arguments) -> tuple[str, ...]:
    parameters = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    names = [argument.arg for argument in parameters]
    if arguments.vararg is not None:
        names.append(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.append(arguments.kwarg.arg)
    return tuple(names)


def _function_scope_nodes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterable[ast.AST]:
    def walk(node: ast.AST) -> Iterable[ast.AST]:
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            yield from walk(child)

    for statement in function.body:
        yield from walk(statement)


def _parameter_passthrough_usage(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: dict[str, str],
    safe_attributes: frozenset[int] = frozenset(),
) -> tuple[
    frozenset[str],
    frozenset[str],
    frozenset[str],
    tuple[str, ...],
    tuple[tuple[ast.Call, str], ...],
]:
    """Return parameter-derived call and return sinks, conservatively."""

    def value_names(
        value: ast.AST, tainted: set[str], *, include_member_access: bool = False
    ) -> set[str]:
        names: set[str] = set()

        def walk(node: ast.AST | None, available: set[str]) -> None:
            if node is None:
                return
            if isinstance(node, ast.Name):
                if node.id in available:
                    names.add(node.id)
                return
            if isinstance(node, ast.Lambda):
                walk(node.body, available - set(_parameters_from_arguments(node.args)))
                return
            if isinstance(node, (ast.Attribute, ast.Subscript)):
                if include_member_access:
                    walk(node.value, available)
                return
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and id(node.func) in safe_attributes:
                    return
                if _qualified_name(node.func, aliases) == "dataclasses.replace":
                    return
                if isinstance(node.func, (ast.Attribute, ast.Subscript)):
                    walk(node.func.value, available)
                else:
                    walk(node.func, available)
                for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
                    walk(argument, available)
                return
            if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                for element in node.elts:
                    walk(element, available)
                return
            if isinstance(node, ast.Dict):
                for item in (*node.keys, *node.values):
                    walk(item, available)
                return
            if isinstance(node, ast.Starred):
                walk(node.value, available)
                return
            if isinstance(node, ast.NamedExpr):
                walk(node.value, available)
                return
            if isinstance(node, ast.Return):
                walk(node.value, available)

        walk(value, tainted)
        return names

    def assignment_taints(target: ast.AST, value: ast.AST, tainted: set[str]) -> set[str]:
        if isinstance(target, ast.Starred):
            return assignment_taints(target.value, value, tainted)
        if isinstance(target, ast.Name):
            if isinstance(value, (ast.Attribute, ast.Subscript)):
                if isinstance(value, ast.Attribute) and id(value) in safe_attributes:
                    return set()
                return {target.id} if value_names(value.value, tainted) else set()
            return {target.id} if value_names(value, tainted) else set()
        if isinstance(target, (ast.Tuple, ast.List)):
            if isinstance(value, (ast.Tuple, ast.List)):
                return {
                    name
                    for nested_target, nested_value in zip(target.elts, value.elts, strict=False)
                    for name in assignment_taints(nested_target, nested_value, tainted)
                }
            if value_names(value, tainted):
                return set(_assignment_names(target))
        return set()

    def nested_function_taints(
        nested: ast.FunctionDef | ast.AsyncFunctionDef, tainted: set[str]
    ) -> bool:
        local = set(_parameters(nested))
        return any(
            value_names(node, tainted - local)
            for statement in nested.body
            for node in ast.walk(statement)
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )

    parameter_names = set(_parameters(function)) - {"cls", "self"}
    parameter_aliases = set(parameter_names)
    nodes = tuple(_function_scope_nodes(function))
    changed = True
    while changed:
        changed = False
        for node in nodes:
            tainted_names: set[str] = set()
            if (
                isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
                and node.value is not None
            ):
                targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
                tainted_names.update(
                    name
                    for target in targets
                    for name in assignment_taints(target, node.value, parameter_aliases)
                )
            elif isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and nested_function_taints(node, parameter_aliases):
                tainted_names.add(node.name)
            if not tainted_names:
                continue
            before = len(parameter_aliases)
            parameter_aliases.update(tainted_names)
            changed = changed or len(parameter_aliases) != before
    called: set[str] = set()
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in parameter_aliases:
            called.add(node.func.id)
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "__call__":
            called.update(value_names(node.func.value, parameter_aliases))
            continue
        if isinstance(node.func, ast.Subscript):
            called.update(value_names(node.func.value, parameter_aliases))
    returned: set[str] = set()
    yielded: set[str] = set()
    assignment_sinks: list[str] = []

    def storage_targets(target: ast.AST) -> Iterable[str]:
        if isinstance(target, ast.Attribute):
            yield f"attribute:{target.attr}"
        elif isinstance(target, ast.Subscript):
            yield "subscript"
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                yield from storage_targets(element)
        elif isinstance(target, ast.Starred):
            yield from storage_targets(target.value)

    for node in nodes:
        if isinstance(node, ast.Return) and node.value is not None:
            returned.update(value_names(node.value, parameter_aliases))
        elif isinstance(node, (ast.Yield, ast.YieldFrom)) and node.value is not None:
            yielded.update(value_names(node.value, parameter_aliases))
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            if value_names(node.value, parameter_aliases, include_member_access=True):
                for target in targets:
                    assignment_sinks.extend(storage_targets(target))
    argument_sinks: list[tuple[ast.Call, str]] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        if _qualified_name(node.func, aliases) == "dataclasses.replace":
            continue
        for index, argument in enumerate(node.args):
            if value_names(argument, parameter_aliases, include_member_access=True):
                argument_sinks.append((node, str(index)))
        for keyword in node.keywords:
            if value_names(keyword.value, parameter_aliases, include_member_access=True):
                argument_sinks.append((node, keyword.arg or "**"))
    return (
        frozenset(called),
        frozenset(returned),
        frozenset(yielded),
        tuple(assignment_sinks),
        tuple(argument_sinks),
    )


def _string_literals(node: ast.AST) -> Iterable[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def _is_dynamic_access_name(qualified: str | None) -> bool:
    return qualified == "getattr" or (
        qualified is not None
        and (qualified.endswith(".getattr") or qualified.endswith(".__getattribute__"))
    )


def _is_dynamic_execution_name(qualified: str | None) -> bool:
    return qualified in DYNAMIC_EXECUTION_REFERENCES


def _is_dynamic_namespace_container(node: ast.AST, aliases: dict[str, str]) -> bool:
    container = node
    if isinstance(container, ast.Attribute) and container.attr == "__dict__":
        return True
    return isinstance(container, ast.Call) and _qualified_name(container.func, aliases) in {
        "builtins.vars",
        "globals",
        "locals",
        "vars",
    }


def _is_dynamic_lookup(node: ast.AST, aliases: dict[str, str]) -> bool:
    if isinstance(node, ast.Subscript):
        return _is_dynamic_namespace_container(node.value, aliases)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and _is_dynamic_namespace_container(node.func.value, aliases)
    ):
        return True
    if not isinstance(node, ast.Call) or not node.args:
        return False
    qualified = _qualified_name(node.func, aliases)
    return qualified in {"dict.__getitem__", "operator.getitem"} and (
        _is_dynamic_namespace_container(node.args[0], aliases)
    )


def _is_unknown_dispatch_call(
    call: ast.Call,
    aliases: dict[str, str],
    local_callables: frozenset[str],
    *,
    filename: str,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    position: str,
) -> bool:
    if _is_dynamic_lookup(call.func, aliases):
        return True
    qualified = _qualified_name(call.func, aliases) or ast.unparse(call.func)
    function_key = (Path(filename).name, function.name)
    if (*function_key, qualified, position) in SAFE_PARAMETER_CALL_SITES:
        expected = SAFE_PARAMETER_CALL_FUNCTION_DIGESTS.get(function_key)
        actual = hashlib.sha256(
            ast.dump(function, annotate_fields=True, include_attributes=False).encode("utf-8")
        ).hexdigest()
        if expected is not None and actual == expected:
            return False
    if qualified in SAFE_PARAMETER_CALLEES:
        return False
    if isinstance(call.func, ast.Name) and call.func.id in local_callables:
        return False
    return qualified not in {
        "all",
        "any",
        "bool",
        "callable",
        "cls",
        "dict",
        "enumerate",
        "float",
        "frozenset",
        "int",
        "isinstance",
        "len",
        "list",
        "max",
        "min",
        "next",
        "range",
        "reversed",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "type",
        "zip",
    }


def _contains_shell_deletion(node: ast.AST) -> bool:
    payload = " ".join(_string_literals(node))
    return SHELL_DELETION.search(re.sub(r"\s+", " ", payload)) is not None


def _function_rebound_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    rebound: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_Assign(self, node: ast.Assign) -> None:
            rebound.update(name for target in node.targets for name in _assignment_names(target))
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            rebound.update(_assignment_names(node.target))
            self.generic_visit(node)

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            rebound.update(_assignment_names(node.target))
            self.generic_visit(node)

        def visit_For(self, node: ast.For) -> None:
            rebound.update(_assignment_names(node.target))
            self.generic_visit(node)

        def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
            rebound.update(_assignment_names(node.target))
            self.generic_visit(node)

        def visit_With(self, node: ast.With) -> None:
            rebound.update(
                name
                for item in node.items
                if item.optional_vars is not None
                for name in _assignment_names(item.optional_vars)
            )
            self.generic_visit(node)

        def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
            rebound.update(
                name
                for item in node.items
                if item.optional_vars is not None
                for name in _assignment_names(item.optional_vars)
            )
            self.generic_visit(node)

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name is not None:
                rebound.add(node.name)
            self.generic_visit(node)

        def visit_comprehension(self, node: ast.comprehension) -> None:
            rebound.update(_assignment_names(node.target))
            self.generic_visit(node)

    visitor = Visitor()
    for statement in function.body:
        visitor.visit(statement)
    return rebound


def _rfc3339_replace_attributes(tree: ast.Module, aliases: dict[str, str]) -> set[int]:
    allowed: set[int] = set()
    datetime_annotations = {"datetime", "datetime.datetime"}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if function.name not in {"_rfc3339", "_canonical_timestamp"}:
            continue
        if len(function.args.args) != 1 or function.args.args[0].arg != "value":
            continue
        value = function.args.args[0]
        if _qualified_name(value.annotation, aliases) not in datetime_annotations:
            continue
        if "value" in _function_rebound_names(function):
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "replace" or len(node.args) != 2 or node.keywords:
                continue
            replace_arguments = tuple(
                argument.value if isinstance(argument, ast.Constant) else None
                for argument in node.args
            )
            if replace_arguments != ("+00:00", "Z"):
                continue
            isoformat = node.func.value
            if not (
                isinstance(isoformat, ast.Call)
                and isinstance(isoformat.func, ast.Attribute)
                and isoformat.func.attr == "isoformat"
                and not isoformat.args
                and len(isoformat.keywords) == 1
                and isoformat.keywords[0].arg == "timespec"
                and isinstance(isoformat.keywords[0].value, ast.Constant)
                and isoformat.keywords[0].value.value == "microseconds"
            ):
                continue
            astimezone = isoformat.func.value
            if not (
                isinstance(astimezone, ast.Call)
                and isinstance(astimezone.func, ast.Attribute)
                and astimezone.func.attr == "astimezone"
                and len(astimezone.args) == 1
                and not astimezone.keywords
                and isinstance(astimezone.args[0], ast.Name)
                and astimezone.args[0].id == "UTC"
                and isinstance(astimezone.func.value, ast.Name)
                and astimezone.func.value.id == "value"
            ):
                continue
            allowed.add(id(node.func))
    return allowed


def _assignment_aliases(tree: ast.Module, aliases: dict[str, str]) -> dict[str, str]:
    normalized = dict(aliases)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        qualified = _qualified_name(node.value, normalized)
        if qualified is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        for target in targets:
            for name in _assignment_names(target):
                normalized[name] = qualified
    return normalized


def _dynamic_dispatch_aliases(tree: ast.Module, aliases: dict[str, str]) -> set[str]:
    names: set[str] = set()

    def bound_names(target: ast.AST, value: ast.AST) -> tuple[str, ...]:
        if isinstance(value, ast.Call) and _is_dynamic_access_name(
            _qualified_name(value.func, aliases)
        ):
            return _assignment_names(target)
        if _is_dynamic_lookup(value, aliases):
            return _assignment_names(target)
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
            return tuple(
                name
                for nested_target, nested_value in zip(target.elts, value.elts, strict=False)
                for name in bound_names(nested_target, nested_value)
            )
        if isinstance(target, ast.Starred):
            return bound_names(target.value, value)
        return ()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        names.update(name for target in targets for name in bound_names(target, node.value))
    return names


def _temporal_replace_attributes(tree: ast.Module, aliases: dict[str, str]) -> set[int]:
    allowed_annotations = {"date", "datetime", "datetime.date", "datetime.datetime"}
    allowed: set[int] = set()

    def position(node: ast.AST, *, after: bool = False) -> tuple[int, int]:
        if after:
            return (getattr(node, "end_lineno", node.lineno), getattr(node, "end_col_offset", 0))
        return (node.lineno, node.col_offset)

    def scope_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterable[ast.AST]:
        def walk(node: ast.AST) -> Iterable[ast.AST]:
            yield node
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
                ):
                    continue
                yield from walk(child)

        for statement in function.body:
            yield from walk(statement)

    control_scopes = (
        ast.If,
        ast.While,
        ast.For,
        ast.AsyncFor,
        ast.Try,
        ast.With,
        ast.AsyncWith,
        ast.Match,
    )
    try_star = getattr(ast, "TryStar", None)
    if try_star is not None:
        control_scopes = (*control_scopes, try_star)

    def control_rebindings(node: ast.AST) -> Iterable[tuple[str, tuple[int, int]]]:
        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.bindings: list[tuple[str, tuple[int, int]]] = []

            def _add_targets(self, targets: Iterable[ast.AST], binding: ast.AST) -> None:
                self.bindings.extend(
                    (name, position(binding))
                    for target in targets
                    for name in _assignment_names(target)
                )

            def visit_FunctionDef(self, nested: ast.FunctionDef) -> None:
                return

            def visit_AsyncFunctionDef(self, nested: ast.AsyncFunctionDef) -> None:
                return

            def visit_Lambda(self, nested: ast.Lambda) -> None:
                return

            def visit_ClassDef(self, nested: ast.ClassDef) -> None:
                return

            def visit_Assign(self, binding: ast.Assign) -> None:
                self._add_targets(binding.targets, binding)
                self.generic_visit(binding)

            def visit_AnnAssign(self, binding: ast.AnnAssign) -> None:
                self._add_targets((binding.target,), binding)
                self.generic_visit(binding)

            def visit_NamedExpr(self, binding: ast.NamedExpr) -> None:
                self._add_targets((binding.target,), binding)
                self.generic_visit(binding)

            def visit_For(self, binding: ast.For) -> None:
                self._add_targets((binding.target,), binding)
                self.generic_visit(binding)

            def visit_AsyncFor(self, binding: ast.AsyncFor) -> None:
                self._add_targets((binding.target,), binding)
                self.generic_visit(binding)

            def visit_With(self, binding: ast.With) -> None:
                self._add_targets(
                    (item.optional_vars for item in binding.items if item.optional_vars), binding
                )
                self.generic_visit(binding)

            def visit_AsyncWith(self, binding: ast.AsyncWith) -> None:
                self._add_targets(
                    (item.optional_vars for item in binding.items if item.optional_vars), binding
                )
                self.generic_visit(binding)

            def visit_ExceptHandler(self, binding: ast.ExceptHandler) -> None:
                if binding.name is not None:
                    self.bindings.append((binding.name, position(binding)))
                self.generic_visit(binding)

            def visit_comprehension(self, binding: ast.comprehension) -> None:
                self._add_targets((binding.target,), binding.target)
                self.generic_visit(binding)

            def visit_MatchAs(self, binding: ast.MatchAs) -> None:
                if binding.name is not None:
                    self.bindings.append((binding.name, position(binding)))
                self.generic_visit(binding)

            def visit_MatchStar(self, binding: ast.MatchStar) -> None:
                if binding.name is not None:
                    self.bindings.append((binding.name, position(binding)))
                self.generic_visit(binding)

            def visit_MatchMapping(self, binding: ast.MatchMapping) -> None:
                if binding.rest is not None:
                    self.bindings.append((binding.rest, position(binding)))
                self.generic_visit(binding)

        visitor = Visitor()
        visitor.visit(node)
        return tuple(visitor.bindings)

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        events: dict[str, list[tuple[tuple[int, int], bool]]] = {}
        control_events: dict[str, list[tuple[int, int]]] = {}
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        ):
            if _qualified_name(argument.annotation, aliases) in allowed_annotations:
                events.setdefault(argument.arg, []).append(((0, 0), True))
        for node in scope_nodes(function):
            if isinstance(node, control_scopes):
                for name, event_position in control_rebindings(node):
                    control_events.setdefault(name, []).append(event_position)
            if isinstance(node, ast.AnnAssign):
                valid = _qualified_name(node.annotation, aliases) in allowed_annotations
                for name in _assignment_names(node.target):
                    events.setdefault(name, []).append((position(node, after=True), valid))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for name in _assignment_names(target):
                        events.setdefault(name, []).append((position(node, after=True), False))
            elif isinstance(node, ast.NamedExpr):
                for name in _assignment_names(node.target):
                    events.setdefault(name, []).append((position(node, after=True), False))
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                for name in _assignment_names(node.target):
                    events.setdefault(name, []).append((position(node), False))
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        for name in _assignment_names(item.optional_vars):
                            events.setdefault(name, []).append((position(node), False))
            elif isinstance(node, ast.ExceptHandler) and node.name is not None:
                events.setdefault(node.name, []).append((position(node), False))
            elif isinstance(node, ast.comprehension):
                for name in _assignment_names(node.target):
                    events.setdefault(name, []).append((position(node.target), False))
        for node in scope_nodes(function):
            if not isinstance(node, ast.Attribute) or node.attr != "replace":
                continue
            if not isinstance(node.value, ast.Name):
                continue
            prior = [event for event in events.get(node.value.id, ()) if event[0] <= position(node)]
            has_prior_control_rebinding = any(
                event_position <= position(node)
                for event_position in control_events.get(node.value.id, ())
            )
            if (
                prior
                and not has_prior_control_rebinding
                and max(prior, key=lambda event: event[0])[1]
            ):
                allowed.add(id(node))
    return allowed


def _is_exact_baseline_callback(
    function: ast.FunctionDef | ast.AsyncFunctionDef, parameter: str
) -> bool:
    """Recognize only the two established, structurally bounded callbacks."""

    calls = [
        node
        for node in _function_scope_nodes(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == parameter
    ]
    if function.name == "build_consolidation_plan" and parameter == "clock":
        if len(calls) != 1 or calls[0].args or calls[0].keywords:
            return False
        body = tuple(
            statement
            for statement in function.body
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            )
        )
        for index, statement in enumerate(body[:-1]):
            if not (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == "created_at"
                and statement.value is calls[0]
            ):
                continue
            validation = body[index + 1]
            return (
                isinstance(validation, ast.Expr)
                and isinstance(validation.value, ast.Call)
                and _qualified_name(validation.value.func, {}) == "require_aware_datetime"
                and len(validation.value.args) == 2
                and isinstance(validation.value.args[0], ast.Name)
                and validation.value.args[0].id == "created_at"
                and isinstance(validation.value.args[1], ast.Constant)
                and validation.value.args[1].value == "clock result"
            )
        return False
    if function.name != "_sorted_unique" or parameter != "key" or len(calls) != 1:
        return False
    call = calls[0]
    if not (
        len(call.args) == 1
        and not call.keywords
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "value"
    ):
        return False
    parents = _parent_map(function)
    parent = parents.get(id(call))
    while parent is not None and not isinstance(parent, ast.GeneratorExp):
        parent = parents.get(id(parent))
    return parent is not None


def _is_exact_baseline_return(
    function: ast.FunctionDef | ast.AsyncFunctionDef, parameter: str, filename: str
) -> bool:
    """Permit only explicitly reviewed parameter-return sites."""

    file_name = Path(filename).name
    if (file_name, function.name, parameter) in SAFE_PARAMETER_RETURN_SITES:
        expected = SAFE_PARAMETER_RETURN_FUNCTION_DIGESTS.get((file_name, function.name))
        actual = hashlib.sha256(
            ast.dump(function, annotate_fields=True, include_attributes=False).encode("utf-8")
        ).hexdigest()
        return expected is not None and actual == expected

    body = [
        statement
        for statement in function.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    if function.name == "_resolved_review" and parameter == "review" and len(body) == 2:
        guarded, fallback = body
        return (
            isinstance(guarded, ast.If)
            and not guarded.orelse
            and isinstance(guarded.test, ast.BoolOp)
            and isinstance(guarded.test.op, ast.Or)
            and len(guarded.test.values) == 2
            and isinstance(guarded.test.values[0], ast.Compare)
            and isinstance(guarded.test.values[0].left, ast.Name)
            and guarded.test.values[0].left.id == "review"
            and len(guarded.test.values[0].ops) == 1
            and isinstance(guarded.test.values[0].ops[0], ast.Is)
            and len(guarded.test.values[0].comparators) == 1
            and isinstance(guarded.test.values[0].comparators[0], ast.Constant)
            and guarded.test.values[0].comparators[0].value is None
            and isinstance(guarded.test.values[1], ast.Name)
            and guarded.test.values[1].id == "compatible"
            and len(guarded.body) == 1
            and isinstance(guarded.body[0], ast.Return)
            and isinstance(guarded.body[0].value, ast.Name)
            and guarded.body[0].value.id == "review"
            and isinstance(fallback, ast.Return)
            and isinstance(fallback.value, ast.Constant)
            and fallback.value.value is None
        )
    if function.name != "_build_signature" or parameter != "file_observation_id" or len(body) != 1:
        return False
    return (
        isinstance(body[0], ast.Return)
        and isinstance(body[0].value, ast.Tuple)
        and len(body[0].value.elts) == 9
        and isinstance(body[0].value.elts[1], ast.Name)
        and body[0].value.elts[1].id == "file_observation_id"
        and all(
            isinstance(item, ast.Attribute)
            and isinstance(item.value, ast.Name)
            and item.value.id == "endpoint"
            for index, item in enumerate(body[0].value.elts)
            if index != 1
        )
    )


def _assignment_targets(node: ast.Assign | ast.AnnAssign | ast.NamedExpr) -> tuple[ast.AST, ...]:
    return node.targets if isinstance(node, ast.Assign) else (node.target,)


def _is_exact_safe_namespace_access(
    node: ast.AST, parents: dict[int, ast.AST], filename: str
) -> bool:
    parent = node
    while id(parent) in parents and not isinstance(parent, ast.Assign):
        parent = parents[id(parent)]
    if not isinstance(parent, ast.Assign):
        return False
    target_names = tuple(name for target in parent.targets for name in _assignment_names(target))
    if target_names != ("__all__",):
        return False
    expected = SAFE_NAMESPACE_ASSIGNMENT_DIGESTS.get((Path(filename).name, "__all__"))
    actual = hashlib.sha256(
        ast.dump(parent, annotate_fields=True, include_attributes=False).encode("utf-8")
    ).hexdigest()
    return expected is not None and actual == expected


def _scan_consolidation_source(source: str, filename: str = "<source>") -> tuple[str, ...]:
    tree = ast.parse(source, filename=filename)
    aliases = _assignment_aliases(tree, _import_aliases(tree))
    parents = _parent_map(tree)
    dispatch_aliases = _dynamic_dispatch_aliases(tree, aliases)
    local_callables = frozenset(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    findings: list[str] = []
    safe_replaces = _rfc3339_replace_attributes(tree, aliases)
    safe_replaces.update(_temporal_replace_attributes(tree, aliases))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] in FORBIDDEN_MODULES:
                    findings.append(f"import:{alias.name}")
                local_name = alias.asname or alias.name
                if FORBIDDEN_PUBLIC_SURFACE.match(local_name):
                    findings.append(f"public-import:{local_name}")
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module.split(".", 1)[0] in FORBIDDEN_MODULES:
                findings.append(f"import:{node.module}")
            for alias in node.names:
                local_name = alias.asname or alias.name
                if FORBIDDEN_PUBLIC_SURFACE.match(local_name):
                    findings.append(f"public-import:{local_name}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            for target in _assignment_targets(node):
                for name in _assignment_names(target):
                    if FORBIDDEN_PUBLIC_SURFACE.match(name):
                        findings.append(f"public:{name}")
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
            if _is_dynamic_access_name(_qualified_name(node.value.func, aliases)):
                findings.append("dynamic-callable-return")
        elif isinstance(node, (ast.Name, ast.Attribute)) and _is_dynamic_execution_name(
            _qualified_name(node, aliases)
        ):
            findings.append("dynamic-execution-reference")
        elif isinstance(node, (ast.Name, ast.Attribute)) and _qualified_name(node, aliases) in {
            "open",
            "builtins.open",
        }:
            findings.append("open-reference")
        elif _is_dynamic_namespace_container(node, aliases) and not (
            _is_exact_safe_namespace_access(node, parents, filename)
        ):
            findings.append("dynamic-namespace-access")
        elif _is_dynamic_lookup(node, aliases):
            findings.append("dynamic-namespace-lookup")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_PATH_METHODS | {
            "open",
            "remove",
            "move",
            "rmtree",
        }:
            if node.attr != "replace" or (
                id(node) not in safe_replaces
                and _qualified_name(node, aliases) != "dataclasses.replace"
            ):
                findings.append(f"attribute:{node.attr}")
        elif isinstance(node, ast.Call):
            qualified = _qualified_name(node.func, aliases)
            if _is_dynamic_namespace_container(node, aliases) and not (
                _is_exact_safe_namespace_access(node, parents, filename)
            ):
                findings.append("dynamic-namespace-access")
            if qualified in FORBIDDEN_CALLS or _is_dynamic_execution_name(qualified):
                findings.append(f"call:{qualified}")
            if isinstance(node.func, ast.Name) and node.func.id == "replace":
                if qualified != "dataclasses.replace":
                    findings.append("call:replace")
            if (isinstance(node.func, ast.Name) and node.func.id == "open") or qualified in {
                "open",
                "builtins.open",
            }:
                findings.append("call:open")
            if isinstance(node.func, ast.Name) and node.func.id in dispatch_aliases:
                findings.append("dynamic-dispatch-alias")
            if isinstance(node.func, ast.Call) and _is_dynamic_access_name(
                _qualified_name(node.func.func, aliases)
            ):
                findings.append("immediate-dynamic-dispatch")
            if _is_dynamic_access_name(qualified) and len(node.args) >= 2:
                attribute = node.args[1]
                if isinstance(attribute, ast.Constant) and attribute.value in (
                    FORBIDDEN_PATH_METHODS | {"LocalCommand", "open", "remove", "unlink"}
                ):
                    findings.append(f"dynamic-access:{attribute.value}")
            if any(
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            ):
                findings.append("shell=True")
            if _contains_shell_deletion(node):
                findings.append("shell-deletion-literal")
    for node in _public_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        else:
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            names = tuple(name for target in targets for name in _assignment_names(target))
            name = names[0] if names else ""
        if FORBIDDEN_PUBLIC_SURFACE.match(name):
            findings.append(f"public:{name}")
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        called, returned, yielded, assignment_sinks, argument_sinks = _parameter_passthrough_usage(
            function, aliases, frozenset(safe_replaces)
        )
        called = frozenset(
            name for name in called if not _is_exact_baseline_callback(function, name)
        )
        returned = frozenset(
            name for name in returned if not _is_exact_baseline_return(function, name, filename)
        )
        findings.extend(f"passthrough-call:{name}" for name in called)
        findings.extend(f"passthrough-return:{name}" for name in returned)
        findings.extend(f"passthrough-yield:{name}" for name in yielded)
        findings.extend(f"passthrough-assignment:{sink}" for sink in assignment_sinks)
        findings.extend(
            "passthrough-argument:"
            f"{_qualified_name(call.func, aliases) or ast.unparse(call.func)}:{position}"
            for call, position in argument_sinks
            if _is_unknown_dispatch_call(
                call,
                aliases,
                local_callables,
                filename=filename,
                function=function,
                position=position,
            )
        )
    return tuple(sorted(set(findings)))


def _command_subcommand(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Tuple) or not node.elts:
        return None
    if any(isinstance(item, ast.Starred) for item in node.elts):
        return None
    first = node.elts[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return None
    if first.value == "--version":
        return "--version" if len(node.elts) == 1 else None
    return None if first.value.startswith("--") else first.value


def _is_fixed_read_command_helper(node: ast.FunctionDef, aliases: dict[str, str]) -> bool:
    if (
        node.name != "_read_command"
        or node.args.posonlyargs
        or len(node.args.args) != 1
        or node.args.args[0].arg != "args"
        or node.args.kwonlyargs
        or node.args.vararg is not None
        or node.args.kwarg is not None
        or node.args.defaults
        or node.args.kw_defaults
        or len(node.body) != 1
        or not isinstance(node.body[0], ast.Return)
        or not isinstance(node.body[0].value, ast.Call)
    ):
        return False
    command = node.body[0].value
    if not _is_local_command_name(_qualified_name(command.func, aliases)) or command.args:
        return False
    if (
        len(
            [
                child
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
                and _is_local_command_name(_qualified_name(child.func, aliases))
            ]
        )
        != 1
    ):
        return False
    keyword_names = {keyword.arg for keyword in command.keywords}
    if None in keyword_names or keyword_names != CALIBRE_DESCRIPTOR_KEYWORDS:
        return False
    return any(
        keyword.arg == "args" and isinstance(keyword.value, ast.Name) and keyword.value.id == "args"
        for keyword in command.keywords
    )


def _is_local_command_name(qualified: str | None) -> bool:
    return qualified == "LocalCommand" or (
        qualified is not None and qualified.endswith(".LocalCommand")
    )


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    return {
        id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
    }


def _enclosing_function(node: ast.AST, parents: dict[int, ast.AST]) -> ast.FunctionDef | None:
    parent = parents.get(id(node))
    while parent is not None:
        if isinstance(parent, ast.FunctionDef):
            return parent
        parent = parents.get(id(parent))
    return None


def _is_allowed_local_command(
    node: ast.Call, parents: dict[int, ast.AST], aliases: dict[str, str]
) -> bool:
    function = _enclosing_function(node, parents)
    if function is None or not _is_fixed_read_command_helper(function, aliases):
        return False
    return function.body[0].value is node


def _is_allowed_calibre_constructor_reference(
    node: ast.AST, parents: dict[int, ast.AST], aliases: dict[str, str]
) -> bool:
    parent = parents.get(id(node))
    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) and parent.returns is node:
        return True
    if not isinstance(parent, ast.Call) or parent.func is not node:
        return False
    qualified = _qualified_name(node, aliases)
    if qualified == "_read_command":
        return True
    return _is_local_command_name(qualified) and _is_allowed_local_command(parent, parents, aliases)


def _contains_calibre_constructor(node: ast.AST, aliases: dict[str, str]) -> bool:
    return any(
        _qualified_name(child, aliases) == "_read_command"
        or _is_local_command_name(_qualified_name(child, aliases))
        for child in ast.walk(node)
        if isinstance(child, (ast.Name, ast.Attribute))
    )


def _scan_calibre_command_shapes(source: str, filename: str = "<source>") -> tuple[str, ...]:
    tree = ast.parse(source, filename=filename)
    aliases = _assignment_aliases(tree, _import_aliases(tree))
    parents = _parent_map(tree)
    local_callables = frozenset(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    findings: list[str] = []

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        defaults = (*function.args.defaults, *function.args.kw_defaults)
        if any(
            default is not None and _contains_calibre_constructor(default, aliases)
            for default in defaults
        ):
            findings.append("command-builder-default")
        called, returned, yielded, assignment_sinks, argument_sinks = _parameter_passthrough_usage(
            function, aliases
        )
        returned = frozenset(
            name for name in returned if not _is_exact_baseline_return(function, name, filename)
        )
        if _is_fixed_read_command_helper(function, aliases):
            called, returned, yielded, assignment_sinks, argument_sinks = (
                frozenset(),
                frozenset(),
                frozenset(),
                (),
                (),
            )
        dynamic_arguments = tuple(
            sink
            for sink in argument_sinks
            if _is_unknown_dispatch_call(
                sink[0],
                aliases,
                local_callables,
                filename=filename,
                function=function,
                position=sink[1],
            )
        )
        if called or returned or yielded or assignment_sinks or dynamic_arguments:
            findings.append("command-builder-passthrough")

    for node in ast.walk(tree):
        if _is_dynamic_namespace_container(node, aliases):
            findings.append("command-builder-dynamic")
        if _is_dynamic_lookup(node, aliases):
            findings.append("command-builder-dynamic")
        if isinstance(node, (ast.Name, ast.Attribute)) and (
            _qualified_name(node, aliases) == "_read_command"
            or _is_local_command_name(_qualified_name(node, aliases))
        ):
            if not _is_allowed_calibre_constructor_reference(node, parents, aliases):
                findings.append("command-builder-reference")
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            assigned = _qualified_name(node.value, aliases)
            if assigned == "_read_command" or _is_local_command_name(assigned):
                findings.append("command-builder-alias")
        if not isinstance(node, ast.Call):
            continue
        qualified = _qualified_name(node.func, aliases)
        if _is_dynamic_access_name(qualified) or (
            isinstance(node.func, ast.Call)
            and _is_dynamic_access_name(_qualified_name(node.func.func, aliases))
        ):
            findings.append("command-builder-dynamic")
        if qualified == "functools.partial" and any(
            _contains_calibre_constructor(argument, aliases) for argument in node.args
        ):
            findings.append("command-builder-partial")
        if qualified == "_read_command":
            if node.keywords or len(node.args) != 1:
                findings.append("read-command-shape")
                continue
            command = _command_subcommand(node.args[0])
            if command is None:
                findings.append("read-command-dynamic-args")
                continue
            if command not in ALLOWED_CALIBRE_SUBCOMMANDS:
                findings.append(f"calibre-subcommand:{command}")
        elif _is_local_command_name(qualified) and not _is_allowed_local_command(
            node, parents, aliases
        ):
            findings.append("direct-local-command")
    return tuple(sorted(set(findings)))


def test_consolidation_package_has_no_mutating_imports_calls_or_public_surfaces() -> None:
    files = _python_files(CONSOLIDATION_ROOT)
    assert files, "expected consolidation package sources"

    findings = [
        f"{path.name}:{finding}"
        for path in files
        for finding in _scan_consolidation_source(path.read_text(encoding="utf-8"), str(path))
    ]

    assert not findings, f"non-execution violations in consolidation package: {findings}"


def test_non_execution_scanner_rejects_adversarial_mutation_shapes() -> None:
    source = """
import importlib as loader
from builtins import getattr as access
from datetime import datetime
from dataclasses import replace
from helpers import helper as execute

execute = object()
get = getattr
load_module = loader.import_module
access_alias = access

class Dangerous:
    apply = callback

    def dispatch(self):
        return access(self, "unlink")()

def inspect(command):
    return command

def mutate(path):
    path.unlink()
    path.rmdir()
    path.rename("target")
    path.replace("target")
    path.write_text("data")
    path.open("w")
    return getattr(path, "unlink")()

@subject.write_text
def decorated():
    return None

defaulted = lambda item=subject.rename: item
(execute := handler)

mutator = subject.unlink
mutator()
untyped_replace = subject.replace
untyped_replace("target")

def dynamic():
    return __import__("pathlib")

loader.import_module("pathlib")
access(runtime, action)
access(runtime, "LocalCommand")
replace(object(), value=1)
datetime.now().replace(year=2027)
run("rm -rf /synthetic")
runner("safe-command", shell=True)
"""
    findings = _scan_consolidation_source(source)

    assert "public:execute" in findings
    assert "public:apply" in findings
    assert "public-import:execute" in findings
    assert "passthrough-return:command" in findings
    assert {"attribute:unlink", "attribute:rmdir", "attribute:rename"} <= set(findings)
    assert {"attribute:replace", "attribute:write_text", "attribute:open"} <= set(findings)
    assert {"call:__import__", "call:importlib.import_module"} <= set(findings)
    assert {"immediate-dynamic-dispatch", "dynamic-access:LocalCommand"} <= set(findings)
    assert "shell=True" in findings
    assert all("datetime.replace" not in finding for finding in findings)
    assert all("dataclasses.replace" not in finding for finding in findings)


def test_non_execution_scanner_allows_only_safe_isoformat_and_dataclass_replace() -> None:
    safe_source = """
import dataclasses as dc
from dataclasses import replace as copied_replace
from datetime import UTC, date, datetime

def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

def revised(value: object) -> object:
    return dc.replace(copied_replace(value, field="safe"), field="safe")

def reschedule(value: datetime, publication_date: date) -> tuple[datetime, date]:
    return value.replace(year=2027), publication_date.replace(year=2027)

def shifted_replace(value: datetime) -> datetime:
    shifted = value.replace
    return shifted(year=2027)

def later_rebinding(value: datetime) -> datetime:
    shifted = value.replace
    value = unknown
    return shifted(year=2027)

def local_annotation() -> datetime:
    local_value: datetime = unknown
    return local_value.replace(year=2027)
"""

    assert _scan_consolidation_source(safe_source) == ()

    typed_replace_source = """
from datetime import datetime

def reassigned(value: datetime) -> object:
    value = unknown
    shifted = value.replace
    return shifted(year=2027)

def for_spoof(value: datetime) -> object:
    for value in values:
        pass
    return value.replace(year=2027)

def with_spoof(value: datetime) -> object:
    with context() as value:
        pass
    return value.replace(year=2027)

def subject_isoformat(subject: object) -> str:
    return subject.isoformat(timespec="microseconds").replace("+00:00", "Z")
"""

    assert {
        "attribute:replace",
        "passthrough-call:shifted",
        "passthrough-return:shifted",
    } <= set(_scan_consolidation_source(typed_replace_source))


@pytest.mark.parametrize(
    "branch",
    (
        """
    if condition:
        value = unknown
    else:
        pass
""",
        """
    if condition:
        pass
    else:
        value = unknown
""",
    ),
)
def test_non_execution_scanner_rejects_temporal_rebinding_in_each_branch_order(
    branch: str,
) -> None:
    source = f"""
from datetime import datetime

def spoof(value: datetime) -> object:
{branch}
    value: datetime = known
    return value.replace(year=2027)
"""

    assert {"attribute:replace", "passthrough-return:value"} <= set(
        _scan_consolidation_source(source)
    )


@pytest.mark.parametrize(
    "control_rebinding",
    (
        """    while condition:
        value = unknown
        break
""",
        """    for value in values:
        pass
""",
        """    try:
        value = unknown
    except Exception:
        pass
""",
        """    with context() as value:
        pass
""",
        """    match subject:
        case _:
            value = unknown
""",
    ),
)
def test_non_execution_scanner_rejects_temporal_rebinding_in_control_scopes(
    control_rebinding: str,
) -> None:
    source = f"""
from datetime import datetime

def spoof(value: datetime) -> object:
{control_rebinding}    value: datetime = known
    return value.replace(year=2027)
"""

    assert {"attribute:replace", "passthrough-return:value"} <= set(
        _scan_consolidation_source(source)
    )


def test_non_execution_scanner_keeps_temporal_replace_before_later_while_rebinding() -> None:
    source = """
from datetime import datetime

def earlier(value: datetime) -> datetime:
    rendered = value.replace(year=2027)
    while condition:
        value = unknown
        break
    return rendered
"""

    assert _scan_consolidation_source(source) == ()


@pytest.mark.parametrize(
    "command",
    (
        "powershell -Command Remove-Item synthetic",
        "pwsh -Command Remove-Item synthetic",
        "bash -c rm synthetic",
        "sudo rm synthetic",
        "cmd /c del synthetic",
    ),
)
def test_non_execution_scanner_rejects_each_shell_deletion_launcher(command: str) -> None:
    findings = _scan_consolidation_source(f"runner({command!r})")

    assert "shell-deletion-literal" in findings


def test_non_execution_scanner_rejects_open_and_dynamic_dispatch_aliases() -> None:
    source = """
from builtins import open as read_file
from builtins import getattr as access

open("synthetic", "r")
read_file("synthetic", "r")
reader = open
reader("synthetic", "r")
dispatch = access(subject, "unlink")
dispatch()
(named_dispatch := access(subject, "unlink"))()
(tuple_dispatch,) = (access(subject, "unlink"),)
tuple_dispatch()
object.__getattribute__(subject, "unlink")()

def passthrough():
    return access(subject, "unlink")
"""
    findings = _scan_consolidation_source(source)

    assert "call:open" in findings
    assert "dynamic-dispatch-alias" in findings
    assert "immediate-dynamic-dispatch" in findings
    assert "dynamic-callable-return" in findings


def test_non_execution_scanner_rejects_generic_callable_passthrough() -> None:
    source = """
from functools import partial

def process(processor, /, x, *more, keyword, **rest):
    direct = processor()
    alias = x
    alias()
    return partial(keyword)

def immediate(processor):
    return partial(processor)()

def _guarded_callback(callback):
    if isinstance(callback, object):
        return callback

def destructure(callback):
    (alias,) = (callback,)
    return alias

def lambda_capture(callback):
    wrapper = lambda: callback
    return wrapper

def function_capture(callback):
    def wrapper():
        return callback
    return wrapper

def protocol_call(callback):
    callback.__call__()

def call_argument(callback):
    consumer(callback)
    consumer(named=callback)
    returned = consumer(callback)
    return returned

def callable_members(callback, container):
    method = callback.method
    method()
    item = container[0]
    item()

def dto_only(record):
    return record.identifier
"""
    findings = _scan_consolidation_source(source)

    assert {"passthrough-call:processor", "passthrough-call:alias"} <= set(findings)
    assert {"passthrough-call:alias", "passthrough-return:keyword"} <= set(findings)
    assert "passthrough-return:callback" in findings
    assert "passthrough-return:wrapper" in findings
    assert "passthrough-call:callback" in findings
    assert {"passthrough-argument:consumer:0", "passthrough-argument:consumer:named"} <= set(
        findings
    )
    assert {"passthrough-call:method", "passthrough-call:item"} <= set(findings)
    assert "passthrough-return:returned" in findings
    assert all("record" not in finding for finding in findings)


def test_non_execution_scanner_rejects_dynamic_execution_references_and_calls() -> None:
    source = """
from builtins import compile as compiler
from builtins import eval as evaluator
from builtins import exec as executor
from importlib import import_module

evaluator
executor("payload")
compiler("payload", "<synthetic>", "exec")
__import__("pathlib")
import_module("pathlib")
"""

    findings = _scan_consolidation_source(source)

    assert "dynamic-execution-reference" in findings
    assert {"call:builtins.exec", "call:builtins.compile", "call:__import__"} <= set(findings)
    assert "call:importlib.import_module" in findings


def test_non_execution_scanner_rejects_storage_and_generator_escapes() -> None:
    source = """
def stash(callback, path, holder, slots):
    holder.callback = callback
    slots[0] = callback
    holder.path = path
    slots[1] = path
    (holder.secondary,) = (callback,)

def leak(callback, path):
    yield callback
    yield from (path,)
"""

    findings = set(_scan_consolidation_source(source))

    assert "passthrough-assignment:attribute:callback" in findings
    assert "passthrough-assignment:attribute:path" in findings
    assert "passthrough-assignment:attribute:secondary" in findings
    assert "passthrough-assignment:subscript" in findings
    assert "passthrough-yield:callback" in findings
    assert "passthrough-yield:path" in findings


def test_non_execution_scanner_rejects_dynamic_namespace_dispatch() -> None:
    source = """
import builtins
import operator
import runtime

builtins.__dict__["eval"]("payload")
vars(builtins)["exec"]("payload")
globals()["compile"]("payload", "<synthetic>", "exec")
locals()["__import__"]("pathlib")
runtime.__dict__["LocalCommand"](args=("remove", "1"))
builtins.__dict__.get("eval")("payload")
vars(builtins).get("exec")("payload")
globals().get("compile")("payload", "<synthetic>", "exec")
operator.getitem(builtins.__dict__, "eval")("payload")
operator.getitem(globals(), "exec")("payload")
dict.__getitem__(globals(), "compile")("payload", "<synthetic>", "exec")
globals().__getitem__("eval")("payload")
vars(builtins).__getitem__("exec")("payload")
builtins.__dict__.__getitem__("compile")("payload", "<synthetic>", "exec")
namespace = globals()
namespace["eval"]("payload")
"""

    findings = set(_scan_consolidation_source(source))

    assert {"dynamic-namespace-access", "dynamic-namespace-lookup"} <= findings


def test_non_execution_scanner_rejects_unreviewed_dispatch_targets() -> None:
    source = """
from plugin import register
import plugin

def local_store(value):
    GLOBAL.append(value)

def expose(callback, registry):
    register(callback)
    plugin.register(callback)
    registry.accept(callback)
    local_store(callback)
"""

    findings = set(_scan_consolidation_source(source))

    assert "passthrough-argument:plugin.register:0" in findings
    assert "passthrough-argument:registry.accept:0" in findings
    assert "passthrough-argument:GLOBAL.append:0" in findings


def test_parameter_return_allowlist_is_bound_to_exact_function_ast() -> None:
    source = """
def build_calibredb_inventory_command(path):
    return path

def _parse_text_list(value, field_name):
    parsed = []
    parsed.append(value)
    return parsed
"""

    consolidation = _scan_consolidation_source(source, "library.py")
    calibre = _scan_calibre_command_shapes(source, "library.py")

    assert "passthrough-return:path" in consolidation
    assert "passthrough-argument:parsed.append:0" in consolidation
    assert "command-builder-passthrough" in calibre


@pytest.mark.parametrize(
    "source",
    (
        "reader = open",
        "def default(reader=open):\n    return reader",
        "from functools import partial\npartial(open)",
    ),
)
def test_non_execution_scanner_rejects_open_reference_shapes(source: str) -> None:
    findings = _scan_consolidation_source(source)

    assert "open-reference" in findings


def test_calibre_library_command_builders_remain_read_only() -> None:
    findings = _scan_calibre_command_shapes(
        CALIBRE_LIBRARY_FILE.read_text(encoding="utf-8"), str(CALIBRE_LIBRARY_FILE)
    )

    assert not findings, f"calibre command builder violations: {findings}"


def test_calibre_command_scanner_rejects_dynamic_and_mutating_shapes() -> None:
    source = """
def _read_command(args):
    return LocalCommand(args=args)

args = ("remove",)
remove = ("remove",)
alias = _read_command
_read_command(args)
_read_command(("remove",))
LocalCommand(args=remove)
alias(("list",))
"""
    findings = _scan_calibre_command_shapes(source)

    assert "read-command-dynamic-args" in findings
    assert "calibre-subcommand:remove" in findings
    assert "direct-local-command" in findings
    assert "command-builder-alias" in findings


@pytest.mark.parametrize(
    "argument",
    (
        "['list']",
        "[*args]",
        "('list', *suffix)",
        "('list' + suffix,)",
        "(f'list',)",
        "('--version', 'list')",
    ),
)
def test_calibre_command_scanner_rejects_nonliteral_or_expanded_command_shapes(
    argument: str,
) -> None:
    source = f"""
def _read_command(args):
    return LocalCommand(
        executable=EXE,
        args=args,
        capability=CAPABILITY,
        timeout_seconds=1.0,
        environment={{}},
        workspace_environment={{}},
        version_policy=POLICY,
        accepted_exit_codes=frozenset({{0}}),
    )

_read_command({argument})
"""

    assert "read-command-dynamic-args" in _scan_calibre_command_shapes(source)


def test_calibre_command_scanner_does_not_match_denylist_text_without_a_command() -> None:
    source = """
FORBIDDEN = {"remove", "export"}
DOCUMENTATION = "remove is prohibited"

def _read_command(args):
    return LocalCommand(
        executable=EXE,
        args=args,
        capability=CAPABILITY,
        timeout_seconds=1.0,
        environment={},
        workspace_environment={},
        version_policy=POLICY,
        accepted_exit_codes=frozenset({0}),
        max_stdout_bytes=1024,
    )

def build():
    return _read_command(("list", "--for-machine"))
"""

    assert _scan_calibre_command_shapes(source) == ()


def test_calibre_command_scanner_rejects_aliases_and_nontrivial_helper_bodies() -> None:
    source = """
from builtins import getattr as access
from functools import partial

command: object = LocalCommand
bound = runtime.LocalCommand
dynamic = access(runtime, "LocalCommand")
dynamic_unknown = access(runtime, requested_constructor)
access(runtime, requested_constructor)()
factory = LocalCommand
factory(args=remove)
bound_factory = partial(factory)
(named_factory := LocalCommand)

def defaults(command=factory, *, secondary=partial(LocalCommand)):
    return command

def passthrough(processor, x):
    processor()
    alias = x
    return alias

def dto_only(record):
    return record.identifier

def _read_command(args):
    first = LocalCommand(
        executable=EXE, args=args, capability=CAPABILITY, timeout_seconds=1.0,
        environment={}, workspace_environment={}, version_policy=POLICY,
        accepted_exit_codes=frozenset({0}),
    )
    return LocalCommand(
        executable=EXE, args=args, capability=CAPABILITY, timeout_seconds=1.0,
        environment={}, workspace_environment={}, version_policy=POLICY,
        accepted_exit_codes=frozenset({0}),
    )
"""

    findings = _scan_calibre_command_shapes(source)

    assert "command-builder-alias" in findings
    assert "command-builder-dynamic" in findings
    assert "direct-local-command" in findings
    assert "command-builder-default" in findings
    assert "command-builder-partial" in findings
    assert "command-builder-passthrough" in findings


def test_calibre_command_scanner_rejects_constructor_reference_escapes() -> None:
    source = """
escaped = (LocalCommand,)
mapping = {"builder": _read_command}
destructured = [LocalCommand]
subscripted = LocalCommand[object]
"""

    findings = _scan_calibre_command_shapes(source)

    assert "command-builder-reference" in findings


def test_calibre_command_scanner_rejects_dynamic_namespace_builders() -> None:
    source = """
import operator
import runtime

globals()["_read_command"](("remove", "1"))
globals().get("_read_command")(("remove", "1"))
operator.getitem(globals(), "_read_command")(("remove", "1"))
globals().__getitem__("_read_command")(("remove", "1"))
namespace = globals()
namespace["_read_command"](("remove", "1"))
runtime.__dict__["LocalCommand"](
    executable="calibredb",
    args=("remove", "1"),
)
"""

    assert "command-builder-dynamic" in _scan_calibre_command_shapes(source)
