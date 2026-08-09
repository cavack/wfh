from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    log_level: str = "INFO"
    environment: str = "production"
    
    # Telegram config (This prevents the AttributeError)
    telegram_token: str | None = None
    telegram_chat_id: str | None = None

    class Config:
        env_file = ".env"

settings = Settings()
