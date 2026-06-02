from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Gemini (vision only — body scan photos)
    gemini_api_key: str
    gemini_model: str = "gemini-2.0-flash"

    # Groq (text generation — NLP parsing, nudges, weekly review)
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"

    # Telegram
    telegram_bot_token: str
    telegram_allowed_user_id: int

    # External APIs
    hevy_api_key: str
    cronometer_api_key: str = ""  # TBD

    # Internal auth (shared secret between pg_cron, bot, and FastAPI)
    internal_secret: str

    # API base URL — used by the bot to POST to FastAPI
    api_base_url: str = "http://localhost:8000"


settings = Settings()
