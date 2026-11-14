"""All thresholds and settings. Defaults below; override with environment variables or .env.

The environment wins over .env (read from the current directory, i.e. the repo root).
Every variable is listed in .env.example.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


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
    language: str = "vi"
    device: str = "auto"  # auto = cuda -> mps -> cpu
    min_free_gb_large: float = 6.0
    min_free_gb_any: float = 3.0
    threads: int = 0  # torch CPU threads; 0 = library default


@dataclass(frozen=True)
class MediaConfig:
    max_duration_s: float = 180.0
    sample_rate: int = 16000
    ffmpeg_threads: int = 2


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
    home: Path | None = None  # data root; None = platformdirs (see storage.paths)
    worker_nice: int = 10  # lower worker CPU priority so the machine stays usable


# env var -> (section, field, type)
_ENV: dict[str, tuple[str, str, type]] = {
    "STUTTERCUT_ASR_MODEL_SIZE": ("asr", "model_size", str),
    "STUTTERCUT_ASR_FALLBACK_SIZE": ("asr", "fallback_size", str),
    "STUTTERCUT_ASR_BACKEND": ("asr", "backend", str),
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
}


def load_config(env: Mapping[str, str] | None = None, dotenv: Path = Path(".env")) -> Config:
    """Defaults, then .env, then the environment (or ``env`` when given, for tests)."""
    values = {**read_dotenv(dotenv), **(os.environ if env is None else env)}
    sections: dict[str, dict[str, object]] = {"asr": {}, "media": {}, "log": {}}
    for name, (section, key, cast) in _ENV.items():
        raw = values.get(name)
        if raw:
            try:
                sections[section][key] = cast(raw)
            except ValueError as e:
                raise ValueError(f"{name}={raw!r} is not a valid {cast.__name__}") from e
    home = values.get("STUTTERCUT_HOME")
    nice = values.get("STUTTERCUT_WORKER_NICE")
    return Config(
        asr=AsrConfig(**sections["asr"]),  # type: ignore[arg-type]
        media=MediaConfig(**sections["media"]),  # type: ignore[arg-type]
        log=LogConfig(**sections["log"]),  # type: ignore[arg-type]
        home=Path(home).expanduser() if home else None,
        worker_nice=int(nice) if nice else 10,
    )
