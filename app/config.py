from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Book Factory"
    app_env: str = "development"
    secret_key: str = "change-me-super-secret"
    database_url: str = "sqlite:///./book_factory.db"
    default_admin_email: str = "admin@example.com"
    default_admin_password: str = "change-me-now"
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    lm_studio_model: str = "gemma-3-27b-it"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-3-27b-it:free"
    request_timeout_seconds: int = 90

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
