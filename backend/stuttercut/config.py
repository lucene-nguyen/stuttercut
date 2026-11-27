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
    # Tests and E2E only: a transcript fixture (tests/fixtures/*.json) replaces the real model.
    fake_fixture: Path | None = None

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
    max_upload_mb: int = 1024
    sample_rate: int = 16000
    ffmpeg_threads: int = 2
    preview_height: int = 480
    preview_sample_rate: int = 48000  # the clean preview's WAV (Web Audio)


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
    num_ctx: int = 6144  # ollama: one chunk + prompt + reply; c001 peak 2.6k (local-llm.md)
    keep_alive: str = "30s"  # bridges chunk requests; the model is unloaded after llm_review
    unload_asr_below_gb: float = 8.0  # local LLM, MPS/CPU: free the ASR model below this free RAM
    expected_gb: float = 6.0  # local LLM size in memory (weights + KV cache at num_ctx)
    vram_margin_gb: float = 1.0  # CUDA: free the ASR model when free VRAM < expected + margin
    load_timeout_s: float = 120.0  # loading the local model before the first chunk
    timeout_s: float = 30.0  # per chunk request
    max_tokens: int = 8000
    chunk_words: int = 150  # keeps a local 8B chunk well under timeout_s (~0.9 s per candidate)
    chunk_overlap_words: int = 30
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


RENDER_FORMATS = ("mp4", "xml", "both")
ENCODERS = ("auto", "h264_videotoolbox", "h264_nvenc", "libx264")


@dataclass(frozen=True)
class RenderConfig:
    """Render of the clean video and FCP XML export (LEARNING-210)."""

    cut_padding_ms: int = 40  # outer cut edges move this much: into silence, or off a neighbour
    cut_merge_ms: int = 50  # cuts closer than this become one
    merge_silent_gap_ms: int = 150  # ... and closer than this when no word sits in the gap
    min_cut_ms: int = 60  # inward padding never makes a cut shorter than this
    min_segment_ms: int = 80  # shorter keep-segments are dropped (cut too)
    join_fade_ms: int = 10  # audio fade out/in at every join: no clicks
    encoder: str = "auto"  # auto = h264_videotoolbox -> h264_nvenc -> libx264
    output_dir: Path | None = None  # None = platformdirs user videos dir / StutterCut

    def __post_init__(self) -> None:
        if self.encoder not in ENCODERS:
            raise ValueError(f"STUTTERCUT_ENCODER must be one of {ENCODERS}, got {self.encoder!r}")


@dataclass(frozen=True)
class LimitsConfig:
    """Worker limits the API's watchdog enforces (LEARNING-235). A step over its timeout or a
    worker over its memory limit is killed; the job fails with that reason, the worker restarts."""

    worker_max_rss_gb: float = 12.0  # worker + its FFmpeg children; a 16 GB Mac keeps 4 GB
    watchdog_interval_s: float = 1.0
    kill_grace_s: float = 5.0  # terminate, then kill after this
    # Step timeout = base + factor x clip length (seconds). Design: 3 min transcribe, 2 min render
    # for a 3-minute clip on the Mac; the factors leave room for a slower first run.
    step_timeout_base_s: float = 60.0
    transcribe_timeout_x: float = 1.5
    llm_timeout_x: float = 1.0
    render_timeout_x: float = 1.0
    other_timeout_x: float = 0.5
    load_model_timeout_s: float = 300.0  # model load: not scaled by clip length
    model_idle_unload_s: float = (
        600.0  # free the ASR model after this long without a job; 0 = never
    )

    def step_timeout_s(self, step: str, clip_s: float | None) -> float:
        if step in ("load_model", "llm_load"):
            return self.load_model_timeout_s
        x = {"transcribe": self.transcribe_timeout_x, "llm_review": self.llm_timeout_x,
             "render": self.render_timeout_x}.get(step, self.other_timeout_x)  # fmt: skip
        return self.step_timeout_base_s + x * (clip_s or 180.0)


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
    render: RenderConfig = field(default_factory=RenderConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    home: Path | None = None  # data root; None = platformdirs (see storage.paths)
    ui_dir: Path | None = None  # built UI the API serves at /; None = <repo>/frontend/dist
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
    "STUTTERCUT_FAKE_TRANSCRIBER": ("asr", "fake_fixture", Path),
    "STUTTERCUT_MAX_DURATION_S": ("media", "max_duration_s", float),
    "STUTTERCUT_MAX_UPLOAD_MB": ("media", "max_upload_mb", int),
    "STUTTERCUT_PREVIEW_HEIGHT": ("media", "preview_height", int),
    "STUTTERCUT_PREVIEW_SAMPLE_RATE": ("media", "preview_sample_rate", int),
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
    "STUTTERCUT_LLM_EXPECTED_GB": ("llm", "expected_gb", float),
    "STUTTERCUT_LLM_VRAM_MARGIN_GB": ("llm", "vram_margin_gb", float),
    "STUTTERCUT_LLM_LOAD_TIMEOUT_S": ("llm", "load_timeout_s", float),
    "STUTTERCUT_CUT_PADDING_MS": ("render", "cut_padding_ms", int),
    "STUTTERCUT_CUT_MERGE_MS": ("render", "cut_merge_ms", int),
    "STUTTERCUT_MERGE_SILENT_GAP_MS": ("render", "merge_silent_gap_ms", int),
    # STUTTERCUT_MIN_CUT_MS is the rule engine's (shortest detected cut); this is render's
    "STUTTERCUT_RENDER_MIN_CUT_MS": ("render", "min_cut_ms", int),
    "STUTTERCUT_MIN_SEGMENT_MS": ("render", "min_segment_ms", int),
    "STUTTERCUT_JOIN_FADE_MS": ("render", "join_fade_ms", int),
    "STUTTERCUT_ENCODER": ("render", "encoder", str),
    "STUTTERCUT_OUTPUT_DIR": ("render", "output_dir", Path),
    "STUTTERCUT_WORKER_MAX_RSS_GB": ("limits", "worker_max_rss_gb", float),
    "STUTTERCUT_WATCHDOG_INTERVAL_S": ("limits", "watchdog_interval_s", float),
    "STUTTERCUT_KILL_GRACE_S": ("limits", "kill_grace_s", float),
    "STUTTERCUT_STEP_TIMEOUT_BASE_S": ("limits", "step_timeout_base_s", float),
    "STUTTERCUT_TRANSCRIBE_TIMEOUT_X": ("limits", "transcribe_timeout_x", float),
    "STUTTERCUT_LLM_TIMEOUT_X": ("limits", "llm_timeout_x", float),
    "STUTTERCUT_RENDER_TIMEOUT_X": ("limits", "render_timeout_x", float),
    "STUTTERCUT_OTHER_TIMEOUT_X": ("limits", "other_timeout_x", float),
    "STUTTERCUT_LOAD_MODEL_TIMEOUT_S": ("limits", "load_model_timeout_s", float),
    "STUTTERCUT_MODEL_IDLE_UNLOAD_S": ("limits", "model_idle_unload_s", float),
}


def load_config(env: Mapping[str, str] | None = None, dotenv: Path = Path(".env")) -> Config:
    """Defaults, then .env, then the environment (or ``env`` when given, for tests)."""
    values = {**read_dotenv(dotenv), **(os.environ if env is None else env)}
    sections: dict[str, dict[str, object]] = {
        "asr": {}, "media": {}, "log": {}, "rules": {}, "llm": {}, "render": {}, "limits": {},
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
    ui_dir = values.get("STUTTERCUT_UI_DIR")
    nice = values.get("STUTTERCUT_WORKER_NICE")
    return Config(
        asr=AsrConfig(**sections["asr"]),  # type: ignore[arg-type]
        media=MediaConfig(**sections["media"]),  # type: ignore[arg-type]
        log=LogConfig(**sections["log"]),  # type: ignore[arg-type]
        rules=RulesConfig(**sections["rules"]),  # type: ignore[arg-type]
        llm=LlmConfig(**sections["llm"]),  # type: ignore[arg-type]
        render=RenderConfig(**sections["render"]),  # type: ignore[arg-type]
        limits=LimitsConfig(**sections["limits"]),  # type: ignore[arg-type]
        home=Path(home).expanduser() if home else None,
        ui_dir=Path(ui_dir).expanduser() if ui_dir else None,
        worker_nice=int(nice) if nice else 10,
    )
