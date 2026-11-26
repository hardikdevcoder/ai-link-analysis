from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Which provider the server uses, and which model
    llm_provider: str = "gemini"          # gemini | anthropic | openai
    llm_model: str = ""
    llm_api_key: str = ""                 # key for the provider above

    # Optional keys, only used by benchmark.py to compare providers
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Public-deployment protection
    rate_limit_per_minute: int = 10       # per IP address
    max_analyses_per_day: int = 200       # whole server, protects your API bill


settings = Settings()