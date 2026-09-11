import pytest

from tg_ifttt.expression.evaluator import evaluate, render_template
from tg_ifttt.expression.errors import UnsafeExpressionError


def test_evaluate_dotted_context():
    context = {"steps": {"start": {"message_id": 42}}}
    assert evaluate("steps.start.message_id", context) == 42


def test_render_template():
    context = {"variables": {"points": 17}}
    assert render_template("积分={{ variables.points }}", context) == "积分=17"


def test_contains_and_regex_match():
    context = {"message": "签到成功，积分：17"}
    assert evaluate('message contains "签到"', context) is True
    assert evaluate(r'regex_match(message, "积分[:：](\\d+)")', context) is True


def test_boolean_and_comparison_operators():
    context = {"points": 17, "enabled": True}
    assert evaluate("enabled and points >= 10", context) is True
    assert evaluate("not (points < 10)", context) is True


@pytest.mark.parametrize(
    "expression",
    ["__import__('os')", "open('secret')", "1 .__class__", "(x for x in [1])"],
)
def test_unsafe_expression_is_rejected(expression):
    with pytest.raises(UnsafeExpressionError):
        evaluate(expression, {})
