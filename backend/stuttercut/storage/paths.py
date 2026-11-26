"""Where state, job files and logs live (platformdirs, or STUTTERCUT_HOME when set)."""

from pathlib import Path

from platformdirs import user_data_path, user_log_path, user_videos_path

from stuttercut.config import Config

APP = "StutterCut"


def data_dir(cfg: Config) -> Path:
    return cfg.home if cfg.home else user_data_path(APP, appauthor=False)


def db_path(cfg: Config) -> Path:
    return data_dir(cfg) / "stuttercut.db"


def job_dir(cfg: Config, job_id: str) -> Path:
    path = data_dir(cfg) / "jobs" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir(cfg: Config) -> Path:
    return cfg.home / "logs" if cfg.home else user_log_path(APP, appauthor=False)


def output_dir(cfg: Config) -> Path:
    """Rendered videos and XML: STUTTERCUT_OUTPUT_DIR, else the user's videos folder."""
    path = cfg.render.output_dir or user_videos_path() / APP
    path.mkdir(parents=True, exist_ok=True)
    return path
