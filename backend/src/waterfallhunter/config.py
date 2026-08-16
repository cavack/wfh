from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env"
    )

    log_level: str = "INFO"
    environment: str = "production"
    registry_db_path: str = (
        "/app/data/waterfall_registry.db"
    )

    # Safety boundary:
    # WaterfallHunter remains signal/paper-only.
    live_trading_enabled: bool = False

    # Temporary, explicitly versioned signal-discovery profile. It never
    # enables order placement and its outcomes remain calibration-pending.
    experimental_pretrigger_enabled: bool = False
    experimental_pretrigger_threshold: float = 45.0

    # LBank execution shadow observation.
    #
    # This feature is observational only:
    # - no scan_eligible mutation
    # - no hunter-state mutation
    # - no trading action
    # - no Telegram signal generation
    #
    # Default OFF so adding the code cannot silently
    # increase production LBank request volume.
    lbank_execution_shadow_enabled: bool = False

    # Operational cadence only. These values are not
    # strategy or execution-suitability thresholds.
    lbank_execution_shadow_batch_size: int = 8
    lbank_execution_shadow_interval_seconds: float = 60.0
    lbank_execution_shadow_success_recheck_seconds: float = 1800.0
    lbank_execution_shadow_failure_recheck_seconds: float = 600.0

    # Telegram config
    telegram_token: str | None = None
    telegram_chat_id: str | None = None

    # Keep the model configurable: model availability is
    # tied to the API key's Google AI project and may change
    # independently of this application.
    gemini_api_key: str | None = None
    gemini_model: str = (
        "gemini-flash-lite-latest"
    )

    ollama_url: str = (
        "http://ollama:11434"
    )

    ollama_model: str = (
        "qwen2.5:3b-instruct"
    )

    # Optional secondary provider for exact exchange/pair
    # futures derivatives.
    #
    # It is never used for price discovery or to fill an
    # unavailable value.
    coinglass_api_key: str | None = None
    coinglass_base_url: str = (
        "https://open-api-v4.coinglass.com"
    )

    # DEX data is discovery context only. A contract mapping
    # is required so a CEX ticker is never guessed to be an
    # unrelated on-chain token.
    dexscreener_enabled: bool = False
    dexscreener_token_map_json: str = "{}"

    etherscan_api_key: str | None = None
    solscan_api_key: str | None = None

    onchain_large_transfer_usd: float = (
        100_000.0
    )


settings = Settings()
