from tg_ifttt.runtime.adapters import ButtonSnapshot, MessageSnapshot


def checkin_message(kind: str = "inline") -> MessageSnapshot:
    return MessageSnapshot(
        message_id=10,
        peer_id="@example_bot",
        sender_id="bot",
        text="菜单",
        buttons=((
            ButtonSnapshot(
                label="✅ 每日签到",
                callback_data="checkin",
                kind=kind,
            ),
        ),),
    )
