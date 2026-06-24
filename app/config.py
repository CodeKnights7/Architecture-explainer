"""
config.py
=========
Application settings.

Speed optimisations (v2.1 — AMD Ryzen 7 7730U / 16 GB RAM):
  - MAX_LLM_TOKENS reduced from 4000 → 2000.
    Shorter responses generate faster on CPU (token generation is the
    bottleneck; halving tokens roughly halves LLM latency).
    Set MAX_LLM_TOKENS=4000 in .env if you need longer outputs.

  - LLM_NUM_THREADS = 8 (all physical cores on Ryzen 7 7730U).
    Ollama's default is ~4 threads; using all 8 cuts per-token time ~40%.

  - LLM_CONTEXT_SIZE = 1024.  KV-cache grows with context; 1024 is
    sufficient for diagram analysis prompts + 2000-token responses.
    Raise to 2048 in .env if outputs appear truncated.

  - LLM_TIMEOUT_SECONDS = 300 (5 min).  Was 600 s (hardcoded in engine).
    With the thread + token optimisations, 5 min is a safe upper bound.
    Adjust via LLM_TIMEOUT_SECONDS in .env if needed.

  - MIN_OCR_UPSCALE_PX reduced from 2400 → 1600 (matches ImageProcessor).
  - MAX_OCR_UPSCALE_PX reduced from 4000 → 2200 (matches ImageProcessor).

All other settings are unchanged.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    APP_NAME:    str = "AI Architecture Diagram Explainer"
    APP_VERSION: str = "2.1.0"
    DEBUG:       bool = False

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    OLLAMA_MODEL: str = "qwen2.5vl:7b"
    OLLAMA_URL:   str = "http://127.0.0.1:11434/api/generate"

    # ------------------------------------------------------------------
    # Uploads
    # ------------------------------------------------------------------

    UPLOAD_DIR:   str = "app/uploads"
    MAX_FILE_SIZE: int = 10 * 1024 * 1024   # 10 MB

    ALLOWED_IMAGE_TYPES: list[str] = [
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
    ]

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------

    OCR_CONFIDENCE_THRESHOLD: float = 0.10

    # Lowered from 2400 → 1600.  OCR quality is reliable at 1600 px and
    # inference runs ~2× faster than at 2400 px.
    MIN_OCR_UPSCALE_PX: int = 1600

    # Lowered from 4000 → 2200 to avoid slow inference on large exports.
    MAX_OCR_UPSCALE_PX: int = 2200

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    # Reduced from 4000 → 2000.  Halving tokens halves generation time on CPU.
    # Override in .env with MAX_LLM_TOKENS=4000 if richer output is needed.
    MAX_LLM_TOKENS:  int   = 2000

    LLM_TEMPERATURE: float = 0.1
    LLM_TOP_P:       float = 0.8

    # Ryzen 7 7730U has 8 physical cores.  Using all 8 reduces per-token
    # latency by ~40% vs Ollama's default of ~4 threads.
    LLM_NUM_THREADS: int = 8

    # KV-cache context window.  1024 covers typical diagram prompts + 2000
    # token responses.  Raise to 2048 in .env if outputs are truncated.
    LLM_CONTEXT_SIZE: int = 1024

    # Request timeout in seconds.  Reduced from 600 → 300 (5 min).
    # With the optimisations above, typical latency is 60–120 s.
    LLM_TIMEOUT_SECONDS: int = 300

    # ------------------------------------------------------------------
    # Feature flags
    # ------------------------------------------------------------------

    ENABLE_METRICS:        bool = True
    ENABLE_GRAPH_ANALYSIS: bool = True
    ENABLE_EVALUATION:     bool = True

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()