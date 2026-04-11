from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Book Factory"
    app_env: str = "development"
    secret_key: str = "change-me-super-secret"
    database_url: str = "sqlite:///./book_factory.db"
    default_admin_email: str = "admin@example.com"
    default_admin_password: str = "change-me-now"
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    lm_studio_api_key: str = ""
    lm_studio_model: str = "gemma-3-27b-it"
    google_api_key: str = ""
    google_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    google_model: str = "gemini-2.5-flash"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openrouter/auto"
    # Public URL of your app (OpenRouter attribution); some proxies require a real https URL
    openrouter_http_referer: str = "https://localhost"
    # Max completion tokens for OpenAI-compatible providers (chapters, SEO); OpenRouter caps per model
    llm_max_output_tokens: int = 8192
    request_timeout_seconds: int = 120
    # Domyślny routing LLM gdy użytkownik nie nadpisze w UI: auto = kolejka LM→Gemini→OpenRouter
    preferred_llm_provider: str = "auto"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
