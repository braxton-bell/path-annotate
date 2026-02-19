from __future__ import annotations

import ast
import concurrent.futures
import datetime
import tomllib
from pathlib import Path
from typing import Any, Literal

import pathspec
import yaml

from codetools.annotate.path_annotate import PathHeaderAnnotator

from . import models
from .ast_ops import AstUtils


class InventoryService:
    """
    Core service for analyzing Python repositories and generating API inventories.
    """

    def __init__(
        self,
        *,
        app_config: dict[str, Any],
        root_path: Path,
    ) -> None:
        self._app_config = app_config
        self._root = root_path

        # Dependencies
        self._path_matcher = self._init_path_matcher()
        self._concurrency = max(1, self._app_config.get("concurrency", 1))

    def run_inventory(self) -> models.InventoryReport:
        """
        Executes the full inventory scan.
        """
        print(f"Starting inventory scan of '{self._root}'")
        start_time = datetime.datetime.now(datetime.timezone.utc)

        pkg_name, pkg_version = self._read_pyproject(
            self._app_config.get("_pyproject_path")
        )

        all_files, excluded_count = self._collect_files()
        packages = self._build_package_tree(all_files)

        # Flatten modules for parallel processing
        all_modules = [m for pkg in packages for m in pkg["modules"]]

        stats = self._init_stats(
            len(all_files), excluded_count, len(packages), len(all_modules)
        )

        if not all_modules:
            return self._build_report(
                start_time, stats, packages, pkg_name, pkg_version
            )

        # Execute Parallel Parsing
        self._process_modules(all_modules, packages, stats)

        return self._build_report(start_time, stats, packages, pkg_name, pkg_version)

    def write_yaml(self, report: models.InventoryReport, path: str) -> None:
        """
        Writes the report to a YAML file.
        """
        data = dict(report)
        out_p = Path(path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with open(out_p, "w", encoding="utf-8") as f:
            self._yaml_dump_no_alias(data, f)

        print(f"Inventory written to: {out_p.resolve()}")

    # --- Private Helpers ---

    def _init_path_matcher(self) -> pathspec.PathSpec | None:
        patterns = self._app_config.get("exclude")
        if patterns:
            try:
                return pathspec.PathSpec.from_lines("gitwildmatch", patterns)
            except Exception as e:
                print(f"WARNING: Invalid exclude patterns: {e}")
        return None

    def _init_stats(
        self, files: int, excluded: int, pkgs: int, mods: int
    ) -> models.InventoryStats:
        return models.InventoryStats(
            files_scanned=files,
            files_excluded=excluded,
            files_parsed_ok=0,
            files_parse_errors=0,
            packages=pkgs,
            modules=mods,
            classes=0,
            methods=0,
            constants=0,
            enums=0,
            functions=0,
        )

    def _collect_files(self) -> tuple[list[Path], int]:
        all_py: list[Path] = []
        excluded = 0
        try:
            for f in self._root.rglob("*.py"):
                if not f.is_file() or f.is_symlink():
                    continue
                try:
                    rel = f.relative_to(self._root).as_posix()
                    if self._path_matcher and self._path_matcher.match_file(rel):
                        excluded += 1
                        continue
                    all_py.append(f)
                except ValueError:
                    continue
        except PermissionError as e:
            print(f"ERROR: Permission denied: {e}")

        return sorted(all_py), excluded

    def _build_package_tree(self, files: list[Path]) -> list[models.PackageRecord]:
        pkg_dirs: set[Path] = {p.parent for p in files}
        if self._app_config.get("package_mode") == "require_init_py":
            pkg_dirs = {p.parent for p in files if p.name == "__init__.py"}

        packages_map: dict[str, models.PackageRecord] = {}

        for p_dir in sorted(list(pkg_dirs)):
            rel = self._normalize_rel(p_dir)
            qname = rel.lstrip("/").replace("/", ".")
            packages_map[rel] = models.PackageRecord(
                path=rel, qname=qname, is_package=True, modules=[]
            )

        for f in files:
            p_rel = self._normalize_rel(f.parent)
            if p_rel in packages_map:
                m_rel = self._normalize_rel(f)
                m_qname = (
                    m_rel.lstrip("/")
                    .replace(".py", "")
                    .replace("/__init__", "")
                    .replace("/", ".")
                )
                packages_map[p_rel]["modules"].append(
                    models.ModuleRecord(
                        path=m_rel,
                        qname=m_qname,
                        docstring=None,
                        classes=[],
                        functions=[],
                        enums=[],
                        constants=[],
                    )
                )

        return list(packages_map.values())

    def _process_modules(
        self,
        all_modules: list[models.ModuleRecord],
        packages: list[models.PackageRecord],
        stats: models.InventoryStats,
    ) -> None:

        parsed_results: dict[str, models.ModuleRecord | str] = {}

        with concurrent.futures.ProcessPoolExecutor(
            max_workers=self._concurrency
        ) as executor:
            futures = {
                executor.submit(
                    ModuleParser.parse_file,
                    self._root / m["path"].lstrip("/"),
                    self._app_config,
                    self._root,
                ): m["qname"]
                for m in all_modules
            }

            for future in concurrent.futures.as_completed(futures):
                qname = futures[future]
                try:
                    _, result = future.result()
                    parsed_results[qname] = result
                except Exception as e:
                    parsed_results[qname] = f"Process Error: {e}"

        # Merge results
        for pkg in packages:
            processed_mods: list[models.ModuleRecord] = []
            for skeleton in pkg["modules"]:
                res = parsed_results.get(skeleton["qname"])
                if isinstance(res, dict):
                    stats["files_parsed_ok"] += 1
                    self._update_stats(stats, res)
                    processed_mods.append(res)
                else:
                    stats["files_parse_errors"] += 1
                    print(f"WARNING: Failed {skeleton['path']}: {res}")

            pkg["modules"] = sorted(processed_mods, key=lambda m: m["qname"])

    def _update_stats(
        self, stats: models.InventoryStats, mod: models.ModuleRecord
    ) -> None:
        stats["constants"] += len(mod.get("constants", []))
        stats["enums"] += len(mod.get("enums", []))
        stats["functions"] += len(mod.get("functions", []))
        stats["classes"] += len(mod["classes"])
        for c in mod["classes"]:
            stats["constants"] += len(c.get("constants", []))
            stats["methods"] += len(c["methods"])

    def _read_pyproject(self, path: str | None) -> tuple[str | None, str | None]:
        if not path:
            return None, None
        p_path = Path(path)
        if not p_path.is_file():
            return None, None
        try:
            with open(p_path, "rb") as f:
                data = tomllib.load(f)

            if "project" in data:
                return data["project"].get("name"), data["project"].get("version")
            if "tool" in data and "poetry" in data["tool"]:
                return data["tool"]["poetry"].get("name"), data["tool"]["poetry"].get(
                    "version"
                )
        except Exception:
            pass
        return None, None

    def _normalize_rel(self, path: Path) -> str:
        rel = PathHeaderAnnotator.normalize_relpath(self._root, path)
        if self._app_config.get("leading_slash_in_paths"):
            return f"/{rel}"
        return rel

    def _build_report(
        self,
        start: datetime.datetime,
        stats: models.InventoryStats,
        pkgs: list[models.PackageRecord],
        pname: str | None,
        pver: str | None,
    ) -> models.InventoryReport:
        clean_conf = self._app_config.copy()
        clean_conf.pop("_pyproject_path", None)

        meta = models.Metadata(
            schema_version="1.0",
            generated_at=start.isoformat().replace("+00:00", "Z"),
            package={"name": pname, "version": pver},
            root=str(self._root),
            config_effective=clean_conf,
        )
        return models.InventoryReport(meta=meta, stats=stats, packages=pkgs)

    def _yaml_dump_no_alias(self, data: Any, stream: Any) -> None:
        class MultilineDumper(yaml.SafeDumper):
            def represent_scalar(self, tag, value, style=None):
                if isinstance(value, str) and "\n" in value:
                    style = "|"
                return super().represent_scalar(tag, value, style)

        class NoAliasDumper(MultilineDumper):
            def ignore_aliases(self, data):
                return True

        yaml.dump(
            data, stream, Dumper=NoAliasDumper, sort_keys=False, allow_unicode=True
        )


class ModuleParser:
    """
    Worker class for parsing individual modules.
    """

    @staticmethod
    def parse_file(
        file_path: Path, config: dict[str, Any], root: Path
    ) -> tuple[str, models.ModuleRecord | str]:

        try:
            # Re-calculate qname inside worker
            rel = PathHeaderAnnotator.normalize_relpath(root, file_path)
            if config.get("leading_slash_in_paths"):
                rel = f"/{rel}"
            qname = (
                rel.lstrip("/")
                .replace(".py", "")
                .replace("/__init__", "")
                .replace("/", ".")
            )
        except Exception as e:
            return str(file_path), f"Path Error: {e}"

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(file_path))

            mod_doc = (
                AstUtils.get_docstring(tree, config.get("strip_docstrings", False))
                if config.get("include_docstrings")
                else None
            )

            # Extract Nodes
            constants, enums, functions, classes = NodeExtractor(config, qname).extract(
                tree.body, "module"
            )

            record = models.ModuleRecord(
                path=rel,
                qname=qname,
                docstring=mod_doc,
                constants=constants,
                enums=enums,
                functions=functions,
                classes=classes,
            )

            # Prune empty optionals
            if not mod_doc:
                record.pop("docstring", None)
            if not config.get("include_constants"):
                record.pop("constants", None)
            if not config.get("include_enums"):
                record.pop("enums", None)
            if not config.get("include_functions"):
                record.pop("functions", None)

            return qname, record
        except Exception as e:
            return qname, f"Parse Error: {e}"


class NodeExtractor:
    # (Same as before, no changes needed here)
    def __init__(self, config: dict[str, Any], parent_qname: str) -> None:
        self.config = config
        self.parent_qname = parent_qname

    def extract(self, nodes: list[ast.stmt], scope: Literal["module", "class"]):
        consts: list[models.ConstantRecord] = []
        enums: list[models.EnumRecord] = []
        funcs: list[models.FunctionRecord] = []
        clss: list[models.ClassRecord] = []

        for node in nodes:
            if self.config.get("include_constants") and isinstance(
                node, (ast.Assign, ast.AnnAssign)
            ):
                if (t := getattr(node, "target", None)) and isinstance(t, ast.Name):
                    if c := self._const(node, scope, t):
                        consts.append(c)

            elif (
                self.config.get("include_functions")
                and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and scope == "module"
            ):
                if self._vis(node.name):
                    funcs.append(self._func(node))

            elif isinstance(node, ast.ClassDef):
                if self._vis(node.name):
                    fq = f"{self.parent_qname}.{node.name}"
                    if self.config.get("include_enums") and AstUtils.is_enum(node):
                        enums.append(self._enum(node, fq))
                    else:
                        clss.append(self._class(node, fq))

        return (
            sorted(consts, key=lambda x: x["name"]),
            sorted(enums, key=lambda x: x["qname"]),
            sorted(funcs, key=lambda x: x["qname"]),
            sorted(clss, key=lambda x: x["qname"]),
        )

    def _vis(self, name: str) -> bool:
        return (
            not self.config.get("public_only")
            or AstUtils.get_visibility(name) == "public"
        )

    def _const(
        self, node: Any, scope: str, target: ast.Name
    ) -> models.ConstantRecord | None:
        name = target.id
        vis = AstUtils.get_visibility(name)
        st = self.config.get("constant_visibility", "no_underscore")

        if st == "uppercase":
            if not (
                name.isupper()
                and AstUtils.re.match(r"^[A-Z0-9_]+$", name)
                and vis == "public"
            ):
                return None
        elif st == "no_underscore" and vis != "public":
            return None

        v, vr = AstUtils.extract_literal_value(getattr(node, "value", None))
        r = models.ConstantRecord(name=name, visibility=vis, scope=scope, value=v, value_repr=vr)  # type: ignore
        if v is None:
            r.pop("value", None)
        return r

    def _func(self, node: Any) -> models.FunctionRecord:
        q = f"{self.parent_qname}.{node.name}"
        _, d = AstUtils.get_decorator_kind(node.decorator_list)
        s = self._sig(node.args, node.returns)
        doc = AstUtils.get_docstring(node, self.config.get("strip_docstrings", False))
        r = models.FunctionRecord(
            name=node.name,
            qname=q,
            visibility=AstUtils.get_visibility(node.name),
            decorators=d,
            signature=s,
            docstring=doc,
        )
        if not doc:
            r.pop("docstring", None)
        return r

    def _class(self, node: ast.ClassDef, qname: str) -> models.ClassRecord:
        doc = AstUtils.get_docstring(node, self.config.get("strip_docstrings", False))
        sub = NodeExtractor(self.config, qname)
        consts, _, _, _ = sub.extract(node.body, "class")

        methods: list[models.MethodRecord] = []
        for i in node.body:
            if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if i.name == "__init__" or self._vis(i.name):
                    methods.append(sub._method(i, qname))

        r = models.ClassRecord(
            name=node.name,
            qname=qname,
            docstring=doc,
            constants=consts,
            methods=sorted(methods, key=lambda x: x["name"]),
        )
        if not doc:
            r.pop("docstring", None)
        if not self.config.get("include_constants"):
            r.pop("constants", None)
        return r

    def _enum(self, node: ast.ClassDef, qname: str) -> models.EnumRecord:
        doc = AstUtils.get_docstring(node, self.config.get("strip_docstrings", False))
        mems = []
        for i in node.body:
            if (
                isinstance(i, (ast.Assign, ast.AnnAssign))
                and (t := getattr(i, "target", None))
                and isinstance(t, ast.Name)
            ):
                if not t.id.startswith("_"):
                    _, vr = AstUtils.extract_literal_value(getattr(i, "value", None))
                    mems.append(models.EnumMemberRecord(name=t.id, value_repr=vr))
        r = models.EnumRecord(
            name=node.name,
            qname=qname,
            docstring=doc,
            members=sorted(mems, key=lambda x: x["name"]),
        )
        if not doc:
            r.pop("docstring", None)
        return r

    def _method(self, node: Any, cq: str) -> models.MethodRecord:
        k, d = AstUtils.get_decorator_kind(node.decorator_list)
        if node.name == "__init__":
            k = "instance"
        doc = AstUtils.get_docstring(node, self.config.get("strip_docstrings", False))
        r = models.MethodRecord(
            name=node.name,
            qname=f"{cq}.{node.name}",
            visibility=AstUtils.get_visibility(node.name),
            kind=k,
            decorators=d,
            signature=self._sig(node.args, node.returns),
            docstring=doc,
        )
        if not doc:
            r.pop("docstring", None)
        return r

    def _sig(
        self, args: ast.arguments, returns: ast.expr | None
    ) -> models.FunctionSignature:
        ps: list[models.Param] = []

        def add(a, k, d=None):
            ps.append(
                models.Param(
                    name=a.arg,
                    kind=k,
                    annotation=AstUtils.unparse_node(a.annotation),
                    default=d,
                )
            )

        for a in args.posonlyargs:
            add(a, "positional_only")

        off = len(args.args) - len(args.defaults)
        for i, a in enumerate(args.args):
            d = AstUtils.unparse_node(args.defaults[i - off]) if i >= off else None
            add(a, "positional_or_keyword", d)

        if args.vararg:
            add(args.vararg, "var_positional")

        for i, a in enumerate(args.kwonlyargs):
            d = (
                AstUtils.unparse_node(args.kw_defaults[i])
                if args.kw_defaults[i]
                else None
            )
            add(a, "keyword_only", d)

        if args.kwarg:
            add(args.kwarg, "var_keyword")

        return models.FunctionSignature(
            params=ps, returns=AstUtils.unparse_node(returns)
        )
