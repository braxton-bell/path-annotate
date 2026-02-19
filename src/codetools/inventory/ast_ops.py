import ast
from typing import Any, Literal, cast


class AstUtils:
    """
    Static utilities for AST analysis and node extraction.
    """

    @staticmethod
    def get_visibility(name: str) -> Literal["public", "private", "dunder"]:
        if name.startswith("__") and name.endswith("__") and len(name) > 4:
            return "dunder"
        if name.startswith("_"):
            return "private"
        return "public"

    @staticmethod
    def unparse_node(node: ast.expr | None) -> str | None:
        if node is None:
            return None
        try:
            return ast.unparse(node)
        except Exception:
            return f"<ast.{type(node).__name__}>"

    @staticmethod
    def get_docstring(
        node: ast.AsyncFunctionDef | ast.FunctionDef | ast.ClassDef | ast.Module,
        strip: bool,
    ) -> str | None:
        try:
            doc = ast.get_docstring(node, clean=False)
            if doc and strip:
                return doc.strip()
            return doc if doc else None
        except Exception:
            return None

    @staticmethod
    def extract_literal_value(  # noqa : ignore
        node: ast.expr | None,
    ) -> tuple[Any | None, str]:
        value_repr = AstUtils.unparse_node(node) or "None"

        if node is None:
            return None, value_repr

        if isinstance(node, ast.Constant):
            val = node.value
            if isinstance(val, (str, int, float, bool, type(None))):
                return val, value_repr

        try:
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                if all(isinstance(e, ast.Constant) for e in node.elts):
                    val = [e.value for e in node.elts]
                    if isinstance(node, ast.Tuple):
                        return tuple(val), value_repr
                    if isinstance(node, ast.Set):
                        return set(val), value_repr
                    return val, value_repr

            if isinstance(node, ast.Dict):
                if all(
                    isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
                    for k, v in zip(node.keys, node.values)
                ):
                    val = {k.value: v.value for k, v in zip(node.keys, node.values)}
                    return val, value_repr
        except Exception:
            pass

        return None, value_repr

    @staticmethod
    def is_enum(node: ast.ClassDef) -> bool:
        enum_names = {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in enum_names:
                return True
            if isinstance(base, ast.Attribute) and base.attr in enum_names:
                return True
        return False

    @staticmethod
    def get_decorator_kind(
        decorators: list[ast.expr],
    ) -> tuple[Literal["instance", "class", "static"], list[str]]:
        kind: Literal["instance", "class", "static"] = "instance"
        decorator_names: list[str] = []

        for deco in decorators:
            if isinstance(deco, ast.Call):
                deco_node = deco.func
            else:
                deco_node = deco

            name = AstUtils.unparse_node(cast(ast.expr, deco_node))
            if name:
                decorator_names.append(name)
                if name.endswith("staticmethod"):
                    kind = "static"
                elif name.endswith("classmethod"):
                    kind = "class"

        return kind, sorted(decorator_names)
