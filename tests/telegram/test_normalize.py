from tg_ifttt.runtime.adapters import match_button
from tg_ifttt.telegram.normalize import normalize_message


class RawCallbackButton:
    def __init__(self, text, data):
        self.text = text
        self.data = data


class RawTextButton:
    def __init__(self, text):
        self.text = text
        self.data = None


class RawMessage:
    def __init__(self, message_id, text, buttons):
        self.id = message_id
        self.message = text
        self.buttons = buttons


def test_inline_buttons_keep_callback_data_and_coordinates():
    message = normalize_message(
        RawMessage("7", "菜单", [[RawCallbackButton("每日签到", b"checkin")]]),
        peer_id="@bot",
        sender_id="bot",
    )
    button = message.buttons[0][0]
    assert message.message_id == 7
    assert button.kind == "inline"
    assert button.callback_data == "checkin"
    assert button.row == 0
    assert button.column == 0


def test_reply_button_has_no_callback_data():
    message = normalize_message(
        RawMessage(8, "菜单", [[RawTextButton("每日签到")]]),
        peer_id="@bot",
        sender_id="bot",
    )
    assert message.buttons[0][0].kind == "reply"
    assert message.buttons[0][0].callback_data is None


def test_position_match_uses_row_and_column():
    message = normalize_message(
        RawMessage(
            9,
            "菜单",
            [[RawTextButton("第一项"), RawTextButton("第二项")], [RawTextButton("第三项")]],
        ),
        peer_id="@bot",
        sender_id="bot",
    )
    button = match_button(message.buttons, {"type": "position", "value": {"row": 1, "column": 0}})
    assert button.label == "第三项"


def test_ambiguous_regex_fails_by_default():
    message = normalize_message(
        RawMessage(10, "菜单", [[RawTextButton("签到"), RawTextButton("签到记录")]]),
        peer_id="@bot",
        sender_id="bot",
    )
    try:
        match_button(message.buttons, {"type": "regex", "value": "签到"})
    except ValueError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous regex unexpectedly matched a button")
