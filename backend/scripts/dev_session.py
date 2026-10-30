"""Выдаёт cookie сессии для локальной разработки и e2e-тестов, когда Telegram не подключён.

    DATA_DIR=.data SESSION_SECRET=... python scripts/dev_session.py --name Артём --role owner

Создаёт участника (если его нет) и печатает значение cookie `bs_session`. Нужен тот же
SESSION_SECRET, что у сервера: без него подделать сессию нельзя.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from itsdangerous import URLSafeTimedSerializer  # noqa: E402

from app import db as database  # noqa: E402
from app import models  # noqa: E402
from app.auth.session import _SALT  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.migrate import upgrade_to_head  # noqa: E402
from app.services import projects, users  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="Артём")
    parser.add_argument("--tg-id", type=int, default=900001)
    parser.add_argument("--username", default="artem")
    parser.add_argument("--role", default="owner", choices=["owner", "director", "team", "guest"])
    args = parser.parse_args()

    settings = get_settings()
    if not settings.session_secret:
        sys.exit("SESSION_SECRET не задан")
    database.init_engine()
    upgrade_to_head()
    with database.session_factory()() as db:
        projects.ensure_default_project(db)
        user = users.upsert_from_telegram(
            db,
            tg_id=args.tg_id,
            username=args.username,
            name=args.name,
            avatar_path=None,
            owner_tg_id=settings.owner_tg_id,
        )
        user.role = args.role
        db.commit()
        uid = db.get(models.User, user.id).id
    print(URLSafeTimedSerializer(settings.session_secret, salt=_SALT).dumps({"uid": uid}))


if __name__ == "__main__":
    main()
