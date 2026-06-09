from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "graffmap"
    POSTGRES_USER: str = "graffmap"
    POSTGRES_PASSWORD: str = "changeme"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Auth
    SECRET_KEY: str = "changeme-generate-with-openssl-rand-hex-32"
    ADMIN_EMAILS: str = ""  # comma-separated list
    MAGIC_LINK_EXPIRE_MINUTES: int = 15
    SESSION_EXPIRE_HOURS: int = 24

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()]

    # Upload
    UPLOAD_PASSWORD: str = "changeme"
    UPLOAD_DIR: str = "/app/uploads"
    PENDING_LOCATION_DIR: str = "/app/pending_location"
    PHOTOS_DIR: str = "/app/photos"
    THUMBNAILS_DIR: str = "/app/thumbnails"
    GEOJSON_PATH: str = "/app/photos.geojson"
    THUMB_SIZE: int = 500

    # App
    APP_URL: str = "http://localhost"

    # SMTP — select mode: host | relay | external
    SMTP_MODE: str = "host"
    SMTP_FROM: str = "noreply@graffmap.local"

    # Option A: VPS host postfix via Docker host-gateway
    SMTP_HOST_GATEWAY: str = "host-gateway"
    SMTP_HOST_PORT: int = 25

    # Option B: relay container (boky/postfix)
    SMTP_RELAY_HOST: str = "smtp-relay"
    SMTP_RELAY_PORT: int = 25

    # Option C: external SMTP server
    SMTP_EXTERNAL_HOST: str = ""
    SMTP_EXTERNAL_PORT: int = 587
    SMTP_EXTERNAL_USER: str = ""
    SMTP_EXTERNAL_PASSWORD: str = ""
    SMTP_EXTERNAL_TLS: bool = True   # STARTTLS on port 587
    SMTP_EXTERNAL_SSL: bool = False  # Implicit TLS on port 465


@lru_cache()
def get_settings() -> Settings:
    return Settings()
