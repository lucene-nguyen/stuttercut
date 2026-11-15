"""All thresholds and settings. Defaults below; override with environment variables or .env.

The environment wins over .env (read from the current directory, i.e. the repo root).
Every variable is listed in .env.example.
"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from stuttercut.asr import PASSES


def read_dotenv(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser: ignores blanks and comments, strips matching quotes."""
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.removeprefix("export ").strip()] = value
    return values


@dataclass(frozen=True)
class AsrConfig:
    model_size: str = "large"  # CrisperWhisper 2.0 size (ADR 0002)
    fallback_size: str = "turbo"  # used when free RAM < min_free_gb_large
    backend: str = "transformers"  # transformers (CPU/CUDA/MPS) or ct2 (CPU/CUDA, one-pass dual)
    passes: str = "verbatim"  # verbatim, or dual = verbatim + intended (about 2x on transformers)
    language: str = "vi"
    device: str = "auto"  # auto = cuda -> mps -> cpu
    min_free_gb_large: float = 6.0
    min_free_gb_any: float = 3.0
    threads: int = 0  # torch CPU threads; 0 = library default

    def __post_init__(self) -> None:
        if self.passes not in PASSES:
            raise ValueError(f"STUTTERCUT_ASR_PASSES must be one of {PASSES}, got {self.passes!r}")
        if self.backend not in ("transformers", "ct2"):
            raise ValueError(
                f"STUTTERCUT_ASR_BACKEND must be transformers or ct2, got {self.backend!r}"
            )


@dataclass(frozen=True)
class MediaConfig:
    max_duration_s: float = 180.0
    sample_rate: int = 16000
    ffmpeg_threads: int = 2


def csv(raw: str) -> tuple[str, ...]:
    """Comma-separated env value -> tuple of stripped, non-empty items."""
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class RulesConfig:
    """Cut detection thresholds (LEARNING-207). Token lists are matched after normalize()."""

    # Hesitation words + CrisperWhisper's non-lexical tokens ([UH], [UM] on Vietnamese c001).
    filler_tokens: tuple[str, ...] = (
        "ờ", "ơ", "ừm", "ưm", "ờm", "ơm", "hm", "hmm", "uh", "um", "à", "ừ",
    )  # fmt: skip
    # Fillers that are also real words; cut only when isolated (see rules.detect).
    ambiguous_fillers: tuple[str, ...] = ("à", "ừ")
    ambiguous_isolation_ms: int = 200
    pause_min_ms: int = 600
    pause_keep_ms: int = 150
    pause_voiced_max_ms: int = 100  # VAD speech inside a gap above this = not a pause
    repeat_max_n: int = 3
    # Vietnamese reduplications that are words, not stutters.
    repeat_keep: tuple[str, ...] = (
        "từ từ", "dần dần", "lâu lâu", "thường thường", "ngày ngày", "người người", "nhà nhà",
    )  # fmt: skip
    retake_window_s: float = 4.0
    retake_min_words: int = 2
    retake_min_hesitation_ms: int = 300  # filler or silence right before the restart
    vad_min_ms: int = 150
    vad_max_ms: int = 1200
    vad_word_margin_ms: int = 80
    # 0.8, not silero's 0.5: at 0.5 a noisy laptop mic made 153 of 161 s "speech" on c001 (tune
    # split) and no pause survived the VAD check. Provisional until labelled clips (lesson 003).
    vad_threshold: float = 0.8
    merge_gap_ms: int = 50
    min_cut_ms: int = 30
    # Review tier: final confidence at or above this is "sure", below is "unsure" (both with
    # and without the LLM review).
    tier_sure_min: float = 0.7


def _bool(raw: str) -> bool:
    if raw.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if raw.strip().lower() in ("0", "false", "no", "off"):
        return False
    raise ValueError(raw)


LLM_PROVIDERS = ("ollama", "anthropic")
# qwen3:8b: strong Vietnamese (119-language pretraining) and JSON, q4 fits 8 GB VRAM / 16 GB Mac
DEFAULT_MODELS = {"ollama": "qwen3:8b", "anthropic": "claude-sonnet-5-5"}


@dataclass(frozen=True)
class LlmConfig:
    """LLM review of cut candidates (LEARNING-208). Only transcript text is sent (ADR 0001)."""

    enabled: bool = False  # opt-in: needs Ollama running, or an API key for anthropic
    provider: str = "ollama"  # ollama (local, nothing leaves the machine) | anthropic
    model: str = ""  # empty = DEFAULT_MODELS[provider]
    api_key: str = field(default="", repr=False)  # LLM_API_KEY in .env; never logged
    effort: str = "medium"  # anthropic output_config.effort: low | medium | high
    ollama_url: str = "http://127.0.0.1:11434"
    num_ctx: int = 8192  # ollama context window (tokens): one chunk + system prompt + reply
    keep_alive: str = "30s"  # bridges chunk requests; the model is unloaded after llm_review
    unload_asr_below_gb: float = 8.0  # local LLM: free the ASR model first when free RAM is lower
    timeout_s: float = 30.0
    max_tokens: int = 8000
    chunk_words: int = 300
    chunk_overlap_words: int = 40
    weight: float = 0.6  # final = (1 - weight) * rule confidence + weight * LLM cut probability
    price_in_per_mtok: float = 2.0  # USD (Sonnet 5.5), for the cost estimate; ollama costs 0
    price_out_per_mtok: float = 10.0
    prompt_file: Path | None = None  # optional override of the built-in system prompt

    def __post_init__(self) -> None:
        if self.provider not in LLM_PROVIDERS:
            raise ValueError(
                f"STUTTERCUT_LLM_PROVIDER must be one of {LLM_PROVIDERS}, got {self.provider!r}"
            )
        if not self.model:
            object.__setattr__(self, "model", DEFAULT_MODELS[self.provider])


@dataclass(frozen=True)
class LogConfig:
    level: str = "INFO"
    max_bytes: int = 5 * 1024 * 1024
    backup_count: int = 3


@dataclass(frozen=True)
class Config:
    asr: AsrConfig = field(default_factory=AsrConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    log: LogConfig = field(default_factory=LogConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    home: Path | None = None  # data root; None = platformdirs (see storage.paths)
    worker_nice: int = 10  # lower worker CPU priority so the machine stays usable


# env var -> (section, field, parser)
_ENV: dict[str, tuple[str, str, Callable[[str], object]]] = {
    "STUTTERCUT_ASR_MODEL_SIZE": ("asr", "model_size", str),
    "STUTTERCUT_ASR_FALLBACK_SIZE": ("asr", "fallback_size", str),
    "STUTTERCUT_ASR_BACKEND": ("asr", "backend", str),
    "STUTTERCUT_ASR_PASSES": ("asr", "passes", str),
    "STUTTERCUT_ASR_LANGUAGE": ("asr", "language", str),
    "STUTTERCUT_DEVICE": ("asr", "device", str),
    "STUTTERCUT_ASR_MIN_FREE_GB_LARGE": ("asr", "min_free_gb_large", float),
    "STUTTERCUT_ASR_MIN_FREE_GB_ANY": ("asr", "min_free_gb_any", float),
    "STUTTERCUT_ASR_THREADS": ("asr", "threads", int),
    "STUTTERCUT_MAX_DURATION_S": ("media", "max_duration_s", float),
    "STUTTERCUT_FFMPEG_THREADS": ("media", "ffmpeg_threads", int),
    "STUTTERCUT_LOG_LEVEL": ("log", "level", str),
    "STUTTERCUT_LOG_MAX_BYTES": ("log", "max_bytes", int),
    "STUTTERCUT_LOG_BACKUP_COUNT": ("log", "backup_count", int),
    "STUTTERCUT_FILLER_TOKENS": ("rules", "filler_tokens", csv),
    "STUTTERCUT_AMBIGUOUS_FILLERS": ("rules", "ambiguous_fillers", csv),
    "STUTTERCUT_AMBIGUOUS_ISOLATION_MS": ("rules", "ambiguous_isolation_ms", int),
    "STUTTERCUT_PAUSE_MIN_MS": ("rules", "pause_min_ms", int),
    "STUTTERCUT_PAUSE_KEEP_MS": ("rules", "pause_keep_ms", int),
    "STUTTERCUT_PAUSE_VOICED_MAX_MS": ("rules", "pause_voiced_max_ms", int),
    "STUTTERCUT_REPEAT_MAX_N": ("rules", "repeat_max_n", int),
    "STUTTERCUT_REPEAT_KEEP": ("rules", "repeat_keep", csv),
    "STUTTERCUT_RETAKE_WINDOW_S": ("rules", "retake_window_s", float),
    "STUTTERCUT_RETAKE_MIN_WORDS": ("rules", "retake_min_words", int),
    "STUTTERCUT_RETAKE_MIN_HESITATION_MS": ("rules", "retake_min_hesitation_ms", int),
    "STUTTERCUT_VAD_MIN_MS": ("rules", "vad_min_ms", int),
    "STUTTERCUT_VAD_MAX_MS": ("rules", "vad_max_ms", int),
    "STUTTERCUT_VAD_WORD_MARGIN_MS": ("rules", "vad_word_margin_ms", int),
    "STUTTERCUT_VAD_THRESHOLD": ("rules", "vad_threshold", float),
    "STUTTERCUT_MERGE_GAP_MS": ("rules", "merge_gap_ms", int),
    "STUTTERCUT_MIN_CUT_MS": ("rules", "min_cut_ms", int),
    "STUTTERCUT_TIER_SURE_MIN": ("rules", "tier_sure_min", float),
    "STUTTERCUT_LLM_ENABLED": ("llm", "enabled", _bool),
    "STUTTERCUT_LLM_PROVIDER": ("llm", "provider", str),
    "STUTTERCUT_LLM_MODEL": ("llm", "model", str),
    "LLM_API_KEY": ("llm", "api_key", str),
    "STUTTERCUT_LLM_EFFORT": ("llm", "effort", str),
    "STUTTERCUT_LLM_TIMEOUT_S": ("llm", "timeout_s", float),
    "STUTTERCUT_LLM_MAX_TOKENS": ("llm", "max_tokens", int),
    "STUTTERCUT_LLM_CHUNK_WORDS": ("llm", "chunk_words", int),
    "STUTTERCUT_LLM_CHUNK_OVERLAP_WORDS": ("llm", "chunk_overlap_words", int),
    "STUTTERCUT_LLM_WEIGHT": ("llm", "weight", float),
    "STUTTERCUT_LLM_PRICE_IN_PER_MTOK": ("llm", "price_in_per_mtok", float),
    "STUTTERCUT_LLM_PRICE_OUT_PER_MTOK": ("llm", "price_out_per_mtok", float),
    "STUTTERCUT_LLM_PROMPT_FILE": ("llm", "prompt_file", Path),
    "STUTTERCUT_OLLAMA_URL": ("llm", "ollama_url", str),
    "STUTTERCUT_LLM_NUM_CTX": ("llm", "num_ctx", int),
    "STUTTERCUT_LLM_KEEP_ALIVE": ("llm", "keep_alive", str),
    "STUTTERCUT_LLM_UNLOAD_ASR_BELOW_GB": ("llm", "unload_asr_below_gb", float),
}


def load_config(env: Mapping[str, str] | None = None, dotenv: Path = Path(".env")) -> Config:
    """Defaults, then .env, then the environment (or ``env`` when given, for tests)."""
    values = {**read_dotenv(dotenv), **(os.environ if env is None else env)}
    sections: dict[str, dict[str, object]] = {
        "asr": {}, "media": {}, "log": {}, "rules": {}, "llm": {},
    }  # fmt: skip
    for name, (section, key, cast) in _ENV.items():
        raw = values.get(name)
        if raw:
            try:
                sections[section][key] = cast(raw)
            except ValueError as e:
                kind = getattr(cast, "__name__", "value").strip("_")
                shown = "***" if name.endswith("API_KEY") else repr(raw)
                raise ValueError(f"{name}={shown} is not a valid {kind}") from e
    home = values.get("STUTTERCUT_HOME")
    nice = values.get("STUTTERCUT_WORKER_NICE")
    return Config(
        asr=AsrConfig(**sections["asr"]),  # type: ignore[arg-type]
        media=MediaConfig(**sections["media"]),  # type: ignore[arg-type]
        log=LogConfig(**sections["log"]),  # type: ignore[arg-type]
        rules=RulesConfig(**sections["rules"]),  # type: ignore[arg-type]
        llm=LlmConfig(**sections["llm"]),  # type: ignore[arg-type]
        home=Path(home).expanduser() if home else None,
        worker_nice=int(nice) if nice else 10,
    )
