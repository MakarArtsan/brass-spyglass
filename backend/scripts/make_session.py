"""Выпускает StringSession юзербота (TG_SESSION) и показывает id чатов (TG_CHAT_ID).

Запускать локально, один раз, под отдельным аккаунтом команды, который добавлен в закрытый чат:

    TG_API_ID=123456 TG_API_HASH=abcdef... python scripts/make_session.py

Спросит номер телефона, код из Telegram и пароль 2FA (если включён). Печатает строку сессии —
её кладём в переменную TG_SESSION на Amvera. Строка равна доступу к аккаунту: никому не показывать,
в репозиторий не коммитить. Ниже скрипт выводит группы аккаунта, чтобы найти id нужного чата.
"""

import asyncio
import os
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main() -> None:
    try:
        api_id, api_hash = int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"]
    except (KeyError, ValueError):
        sys.exit("Задайте TG_API_ID и TG_API_HASH: https://my.telegram.org → API development tools")

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        me = await client.get_me()
        print(f"\nВошли как {me.first_name} (@{me.username}, id {me.id})\n")
        print("TG_SESSION=" + client.session.save())  # type: ignore[union-attr]
        print("\nГруппы аккаунта (TG_CHAT_ID — это id, у супергрупп он вида -100…):")
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                forum = " [темы]" if getattr(dialog.entity, "forum", False) else ""
                print(f"  {dialog.id:>16}  {dialog.name}{forum}")


if __name__ == "__main__":
    asyncio.run(main())
