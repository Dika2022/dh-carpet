from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Настройки приложения, загружаемые только из переменных окружения."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str
    postgres_host: str
    postgres_port: int = Field(gt=0, le=65535)
    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr | None = None
    postgres_password_file: Path | None = None
    redis_host: str
    redis_port: int = Field(gt=0, le=65535)
    qdrant_host: str
    qdrant_port: int = Field(gt=0, le=65535)
    service_check_timeout_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def load_postgres_password(self) -> "Settings":
        if self.postgres_password_file is not None:
            try:
                password = self.postgres_password_file.read_text(
                    encoding="utf-8"
                ).rstrip("\r\n")
            except OSError as error:
                raise ValueError(
                    "Не удалось прочитать файл из POSTGRES_PASSWORD_FILE: "
                    f"{self.postgres_password_file}"
                ) from error
            if not password:
                raise ValueError("Файл POSTGRES_PASSWORD_FILE не должен быть пустым")
            self.postgres_password = SecretStr(password)

        if (
            self.postgres_password is None
            or not self.postgres_password.get_secret_value()
        ):
            raise ValueError(
                "Нужно задать POSTGRES_PASSWORD или POSTGRES_PASSWORD_FILE"
            )
        return self

    @property
    def database_url(self) -> URL:
        if self.postgres_password is None:  # Защита для статической типизации.
            raise RuntimeError("Пароль PostgreSQL не загружен")
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
