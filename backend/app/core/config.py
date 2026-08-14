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
    internal_api_key: SecretStr | None = None
    internal_api_key_file: Path | None = None

    @model_validator(mode="after")
    def load_file_secrets(self) -> "Settings":
        if self.postgres_password_file is not None:
            self.postgres_password = SecretStr(
                self._read_secret_file(
                    self.postgres_password_file, "POSTGRES_PASSWORD_FILE"
                )
            )

        if self.internal_api_key_file is not None:
            self.internal_api_key = SecretStr(
                self._read_secret_file(
                    self.internal_api_key_file, "INTERNAL_API_KEY_FILE"
                )
            )

        if (
            self.postgres_password is None
            or not self.postgres_password.get_secret_value()
        ):
            raise ValueError(
                "Нужно задать POSTGRES_PASSWORD или POSTGRES_PASSWORD_FILE"
            )
        return self

    @staticmethod
    def _read_secret_file(path: Path, variable_name: str) -> str:
        try:
            secret = path.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as error:
            raise ValueError(
                f"Не удалось прочитать файл из {variable_name}: {path}"
            ) from error
        if not secret:
            raise ValueError(f"Файл {variable_name} не должен быть пустым")
        return secret

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
