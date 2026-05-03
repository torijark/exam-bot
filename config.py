from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str
    OPENAI_API_KEY: str
    ADMIN_ID: int | None = None
    GPT_MODEL: str = "gpt-4o-mini"
    WHISPER_MODEL: str = "whisper-1"

settings = Settings()
