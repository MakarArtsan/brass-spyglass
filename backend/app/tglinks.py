"""Адреса сообщений Telegram: «Открыть в Telegram» на карточке файла."""


def message_url(chat_id: int | None, topic_id: int | None, message_id: int | None) -> str | None:
    """`https://t.me/c/<чат>/<тема>/<сообщение>` для закрытых супергрупп (id вида -100…).

    У общей темы (id 1) и у чата без тем адрес короче. Для обычных групп публичной ссылки нет.
    """
    if chat_id is None or message_id is None:
        return None
    text = str(chat_id)
    if not text.startswith("-100"):
        return None
    chat = text[4:]
    if topic_id in (None, 0, 1):
        return f"https://t.me/c/{chat}/{message_id}"
    return f"https://t.me/c/{chat}/{topic_id}/{message_id}"
