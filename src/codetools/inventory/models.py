from typing import Any, Literal, TypedDict


class Param(TypedDict):
    name: str
    kind: Literal[
        "positional_only",
        "positional_or_keyword",
        "var_positional",
        "keyword_only",
        "var_keyword",
    ]
    annotation: str | None
    default: str | None


class FunctionSignature(TypedDict):
    params: list[Param]
    returns: str | None


class ConstantRecord(TypedDict):
    name: str
    visibility: Literal["public", "private", "dunder"]
    scope: Literal["module", "class"]
    value: Any | None
    value_repr: str


class EnumMemberRecord(TypedDict):
    name: str
    value_repr: str


class EnumRecord(TypedDict):
    name: str
    qname: str
    docstring: str | None
    members: list[EnumMemberRecord]


class MethodRecord(TypedDict):
    name: str
    qname: str
    visibility: Literal["public", "private", "dunder"]
    kind: Literal["instance", "class", "static"]
    decorators: list[str]
    signature: FunctionSignature
    docstring: str | None


class FunctionRecord(TypedDict):
    name: str
    qname: str
    visibility: Literal["public", "private", "dunder"]
    decorators: list[str]
    signature: FunctionSignature
    docstring: str | None


class ClassRecord(TypedDict):
    name: str
    qname: str
    docstring: str | None
    constants: list[ConstantRecord]
    methods: list[MethodRecord]


class ModuleRecord(TypedDict):
    path: str
    qname: str
    docstring: str | None
    constants: list[ConstantRecord]
    enums: list[EnumRecord]
    functions: list[FunctionRecord]
    classes: list[ClassRecord]


class PackageRecord(TypedDict):
    path: str
    qname: str
    is_package: Literal[True]
    modules: list[ModuleRecord]


class InventoryStats(TypedDict):
    files_scanned: int
    files_excluded: int
    files_parsed_ok: int
    files_parse_errors: int
    packages: int
    modules: int
    classes: int
    methods: int
    constants: int
    enums: int
    functions: int


class Metadata(TypedDict):
    schema_version: str
    generated_at: str
    package: dict[str, str | None]
    root: str
    config_effective: dict[str, Any]


class InventoryReport(TypedDict):
    meta: Metadata
    stats: InventoryStats
    packages: list[PackageRecord]
