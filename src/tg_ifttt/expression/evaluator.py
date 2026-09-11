import ast
import operator
import re
from collections.abc import Mapping
from typing import Any, Callable, Dict

from .errors import UnsafeExpressionError


_CONTAINS_PATTERN = re.compile(
    r"^\s*(?P<left>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s+contains\s+(?P<right>.+?)\s*$"
)
_TEMPLATE_PATTERN = re.compile(r"\{\{\s*(.*?)\s*\}\}")
_MAX_DEPTH = 32


def _validate_value(value: Any, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        raise UnsafeExpressionError("context is too deeply nested")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or key.startswith("_"):
                raise UnsafeExpressionError("context keys must be public strings")
            _validate_value(item, depth + 1)
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _validate_value(item, depth + 1)
        return value
    raise UnsafeExpressionError("context contains an unsupported value")


def contains(value: Any, needle: Any) -> bool:
    if isinstance(value, (str, bytes, list, tuple, set, frozenset, dict)):
        return needle in value
    return False


def regex_match(value: Any, pattern: str) -> bool:
    if not isinstance(value, str) or not isinstance(pattern, str):
        return False
    if len(pattern) > 512:
        raise UnsafeExpressionError("regular expression is too long")
    try:
        return re.search(pattern, value) is not None
    except re.error as exc:
        raise UnsafeExpressionError("invalid regular expression: %s" % exc) from exc


HELPERS: Dict[str, Callable[..., Any]] = {
    "contains": contains,
    "regex_match": regex_match,
}


def _normalize_contains(expression: str) -> str:
    match = _CONTAINS_PATTERN.fullmatch(expression)
    if match is None:
        return expression
    return "contains(%s, %s)" % (match.group("left"), match.group("right"))


class _SafeEvaluator:
    def __init__(self, context: Mapping[str, Any]) -> None:
        self.context = context
        self.depth = 0

    def evaluate(self, tree: ast.AST) -> Any:
        return self.visit(tree)

    def visit(self, node: ast.AST) -> Any:
        self.depth += 1
        if self.depth > _MAX_DEPTH:
            raise UnsafeExpressionError("expression is too deeply nested")
        try:
            method = getattr(self, "visit_%s" % type(node).__name__, None)
            if method is None:
                raise UnsafeExpressionError(
                    "expression node is not allowed: %s" % type(node).__name__
                )
            return method(node)
        finally:
            self.depth -= 1

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            raise UnsafeExpressionError("constant type is not allowed")
        return node.value

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id.startswith("_") or node.id not in self.context:
            raise UnsafeExpressionError("unknown name: %s" % node.id)
        return _validate_value(self.context[node.id])

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        if node.attr.startswith("_"):
            raise UnsafeExpressionError("private attributes are not allowed")
        base = self.visit(node.value)
        if not isinstance(base, Mapping) or node.attr not in base:
            raise UnsafeExpressionError("unknown context path: %s" % node.attr)
        return _validate_value(base[node.attr])

    def visit_List(self, node: ast.List) -> Any:
        return [self.visit(item) for item in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        return tuple(self.visit(item) for item in node.elts)

    def visit_Dict(self, node: ast.Dict) -> Any:
        return {self.visit(key): self.visit(value) for key, value in zip(node.keys, node.values)}

    def visit_BoolOp(self, node: ast.BoolOp) -> bool:
        if isinstance(node.op, ast.And):
            for value in node.values:
                if not self.visit(value):
                    return False
            return True
        if isinstance(node.op, ast.Or):
            for value in node.values:
                if self.visit(value):
                    return True
            return False
        raise UnsafeExpressionError("boolean operator is not allowed")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        value = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return +value
        raise UnsafeExpressionError("unary operator is not allowed")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        operations = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Mod: operator.mod,
        }
        operation = next((fn for kind, fn in operations.items() if isinstance(node.op, kind)), None)
        if operation is None:
            raise UnsafeExpressionError("binary operator is not allowed")
        try:
            return operation(self.visit(node.left), self.visit(node.right))
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise UnsafeExpressionError("invalid binary operation") from exc

    def visit_Compare(self, node: ast.Compare) -> bool:
        left = self.visit(node.left)
        comparators = zip(node.ops, node.comparators)
        for operation, comparator in comparators:
            right = self.visit(comparator)
            try:
                if isinstance(operation, ast.Eq):
                    matched = left == right
                elif isinstance(operation, ast.NotEq):
                    matched = left != right
                elif isinstance(operation, ast.Lt):
                    matched = left < right
                elif isinstance(operation, ast.LtE):
                    matched = left <= right
                elif isinstance(operation, ast.Gt):
                    matched = left > right
                elif isinstance(operation, ast.GtE):
                    matched = left >= right
                elif isinstance(operation, ast.In):
                    matched = left in right
                elif isinstance(operation, ast.NotIn):
                    matched = left not in right
                else:
                    raise UnsafeExpressionError("comparison operator is not allowed")
            except TypeError as exc:
                raise UnsafeExpressionError("invalid comparison") from exc
            if not matched:
                return False
            left = right
        return True

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name) or node.func.id not in HELPERS:
            raise UnsafeExpressionError("function is not allowed")
        if node.keywords:
            raise UnsafeExpressionError("keyword arguments are not allowed")
        helper = HELPERS[node.func.id]
        try:
            return helper(*(self.visit(argument) for argument in node.args))
        except TypeError as exc:
            raise UnsafeExpressionError("invalid helper arguments") from exc

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        raise UnsafeExpressionError("subscript access is not allowed")


def evaluate(expression: str, context: Mapping[str, Any]) -> Any:
    if not isinstance(expression, str) or not expression.strip():
        raise UnsafeExpressionError("expression must be a non-empty string")
    normalized = _normalize_contains(expression)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError("invalid expression syntax") from exc
    return _SafeEvaluator(context).evaluate(tree)


def render_template(text: str, context: Mapping[str, Any]) -> str:
    if not isinstance(text, str):
        raise UnsafeExpressionError("template must be a string")

    def replace(match: re.Match) -> str:
        value = evaluate(match.group(1), context)
        return "" if value is None else str(value)

    return _TEMPLATE_PATTERN.sub(replace, text)
