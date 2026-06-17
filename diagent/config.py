from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    database_url: str = "postgresql+asyncpg://diagent:diagent@localhost:5432/diagent"
    redis_url: str = "redis://localhost:6379/0"
    diagent_judge_backend: str = "openai"
    judge_rate_limit_seconds: float = 1.0
    tool_loop_threshold: int = 3
    cost_spike_multiplier: float = 5.0
    latency_spike_ms: int = 30000
    stale_data_hours: float = 72.0
    tool_failure_rate: float = 0.5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
