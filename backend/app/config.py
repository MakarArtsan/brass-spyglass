from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения Amvera. Список — в .env.example."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("/data")
    frontend_dir: Path | None = None  # собранный фронтенд; по умолчанию frontend/dist
    # Excel-трекер для стартовых данных. Не задан — берётся seed/ рядом с приложением,
    # пустая строка отключает автоимпорт.
    seed_xlsx: str | None = None

    tg_api_id: int | None = None
    tg_api_hash: str = ""
    tg_session: str = ""  # StringSession юзербота
    tg_bot_token: str = ""
    tg_bot_username: str = ""  # необязательно: иначе берём через get_me()
    tg_chat_id: int | None = None  # закрытый чат команды
    owner_tg_id: int | None = None

    session_secret: str = ""
    session_days: int = 30
    cookie_secure: bool = True
    login_token_ttl_sec: int = 300
    file_link_ttl_sec: int = 3600  # срок жизни подписанных ссылок на файлы
    membership_recheck_hours: int = 24

    @computed_field  # type: ignore[prop-decorator]
    @property
    def db_path(self) -> Path:
        return self.data_dir / "db" / "app.sqlite"

    @property
    def seed_path(self) -> Path | None:
        if self.seed_xlsx is None:
            return Path(__file__).resolve().parent.parent / "seed" / "Krivoe_zerkalo_tracker.xlsx"
        return Path(self.seed_xlsx) if self.seed_xlsx else None

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def telegram_configured(self) -> bool:
        return bool(self.tg_api_id and self.tg_api_hash and self.tg_bot_token)

    def ensure_dirs(self) -> None:
        for path in (
            self.db_path.parent,
            self.files_dir,
            self.cache_dir,
            self.exports_dir,
            self.backups_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
