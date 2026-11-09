"""Runtime configuration. Everything comes from the environment; nothing is hard-coded."""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent      # backend/ - the service never reads outside it


def _env_file() -> Path:
    """backend/.env, or whatever ENV_FILE names (relative paths resolve from backend/)."""
    named = os.environ.get("ENV_FILE")
    if not named:
        return BASE / ".env"
    p = Path(named).expanduser()
    return p if p.is_absolute() else (BASE / p).resolve()


def _load_env():
    """
    Read the .env file into the environment. Real environment variables always
    take precedence, so a server can configure everything without the file.
    """
    candidate = _env_file()
    if not candidate.exists():
        return
    try:
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
    except OSError:
        pass


_load_env()


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list:
    return [x.strip().rstrip("/") for x in os.environ.get(name, default).split(",") if x.strip()]


def _path(name: str, default: Path) -> str:
    """A path setting; relative values resolve from backend/, not the working directory."""
    value = os.environ.get(name)
    if not value:
        return str(default)
    p = Path(value).expanduser()
    return str(p if p.is_absolute() else (BASE / p).resolve())


class Settings:
    # --- connection -------------------------------------------------------
    MONGO_URI: str = os.environ.get("MONGO_URI", "")
    ENV_FILES: list = [str(p) for p in (_env_file(),) if p.exists()]
    DB_NAME: str = os.environ.get("DB_NAME", "Top40ThinkTanks")
    MASTER: str = os.environ.get("MASTER_COLLECTION", "top_40_think_tanks")

    # --- safety limits ----------------------------------------------------
    MAX_TIME_MS: int = int(os.environ.get("MAX_TIME_MS", "20000"))
    MAX_PAGE_SIZE: int = int(os.environ.get("MAX_PAGE_SIZE", "100"))
    MAX_SKIP: int = int(os.environ.get("MAX_SKIP", "10000"))
    MAX_EXPORT_ROWS: int = int(os.environ.get("MAX_EXPORT_ROWS", "5000"))
    MAX_PIPELINE_STAGES: int = int(os.environ.get("MAX_PIPELINE_STAGES", "24"))
    MAX_SCAN_DOCS: int = int(os.environ.get("MAX_SCAN_DOCS", "60000"))

    # --- behaviour --------------------------------------------------------
    DEMO_MODE: bool = _bool("DEMO_MODE", False)
    KNOWLEDGE_PATH: str = _path("KNOWLEDGE_PATH", BASE / "data" / "corpus_knowledge.json")
    # Demo mode keeps its own snapshot so fixture numbers never replace the real ones.
    STATS_PATH: str = _path("STATS_PATH", BASE / "data" / ("stats.demo.json" if DEMO_MODE
                                                            else "stats.json"))
    # Run the weekly statistics job inside this process. With several workers,
    # turn it off and schedule compute_stats.py instead, or every worker runs it.
    STATS_SCHEDULER: bool = _bool("STATS_SCHEDULER", True)

    # --- the frontend -----------------------------------------------------
    # Origins allowed to call the API from a browser: the frontend's address,
    # scheme and host and port, no path. "*" allows any origin.
    ALLOW_ORIGINS: list = _list("ALLOW_ORIGINS", "http://localhost:5173,http://localhost:4173")

    # --- optional LLM query generation -----------------------------------
    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
    LLM_MODEL: str = os.environ.get("LLM_MODEL", "claude-sonnet-4-5")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY)


settings = Settings()
