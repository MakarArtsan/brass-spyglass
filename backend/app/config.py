from functools import lru_cache
from pathlib import Path

from pydantic import computed_field, field_validator
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
    # Суперадмины (создают проекты, видят все): tg_id через запятую; OWNER_TG_ID — тоже суперадмин.
    superadmin_tg_ids: str = ""

    session_secret: str = ""
    session_days: int = 30
    cookie_secure: bool = True
    login_token_ttl_sec: int = 300
    file_link_ttl_sec: int = 3600  # срок жизни подписанных ссылок на файлы
    # Размер куска при загрузке. Если вход Amvera режет тело запроса (413), поставьте 1.
    upload_chunk_mb: int = 8
    # Кэш просмотра не скачанных файлов Telegram: старые файлы удаляются, когда кэш больше этого.
    tg_preview_cache_mb: int = 500
    # Участников проектов сверяют со списками их чатов раз в столько часов (и по событиям чата).
    members_sync_hours: int = 6
    # Любой пользователь Telegram может войти и создать свой проект. SELF_SERVICE_PROJECTS=false
    # возвращает прежнее правило: входят участники чатов проектов, проекты создаёт суперадмин.
    self_service_projects: bool = True
    new_project_storage_gb: float = 1.0  # лимит места нового проекта (меняет суперадмин)
    # В скольких проектах один человек может быть владельцем (суперадмина не касается).
    max_projects_per_user: int = 3
    # Диск тарифа целиком: его делят все проекты; загрузка, что его переполнит, отклоняется.
    disk_total_gb: float = 5.0
    # Юзербот недоступен: вход работает по последней подтверждённой проверке не старше этого срока.
    members_fallback_hours: int = 72
    # Сжатие картинок при загрузке. Выключатель на случай сбоя; пути к кодировщикам — для тестов.
    compress_images: bool = True
    pngquant_bin: str = "pngquant"
    cjpeg_bin: str = "/opt/mozjpeg/bin/cjpeg"  # mozjpeg собирается в Dockerfile
    originals_keep_days: int = 7  # сколько лежит оригинал до сжатия

    @field_validator("tg_session", mode="before")
    @classmethod
    def _clean_session(cls, value: object) -> object:
        """StringSession — одна длинная строка base64 без пробелов. При копировании в переменную
        легко прихватить кавычки, пробелы или перенос строки: убираем их, а не падаем."""
        if isinstance(value, str):
            return "".join(value.split()).strip("'\"")
        return value

    @property
    def superadmins(self) -> frozenset[int]:
        ids = {
            int(p)
            for p in self.superadmin_tg_ids.replace(";", ",").split(",")
            if p.strip().lstrip("-").isdigit()
        }
        if self.owner_tg_id is not None:
            ids.add(self.owner_tg_id)
        return frozenset(ids)

    def is_superadmin(self, tg_id: int | None) -> bool:
        return tg_id is not None and tg_id in self.superadmins

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
    def tg_thumbs_dir(self) -> Path:
        return self.cache_dir / "tg-thumbs"

    @property
    def tg_view_dir(self) -> Path:
        return self.cache_dir / "tg-view"

    @property
    def tg_tmp_dir(self) -> Path:
        return self.cache_dir / "tg-tmp"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

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
            self.originals_dir,
            self.cache_dir,
            self.exports_dir,
            self.backups_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
