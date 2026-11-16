"""Hybrid model registry: the folder decides what exists, the DB decides what users see.

Scanning upserts one LLMModel row per *.rkllm file under MODELS_DIR. New rows start
disabled. The <=4B policy is enforced with measurable proxies because the .rkllm format
cannot report its parameter count:
  1. file size cap (MAX_MODEL_FILE_GB)        -> status "too_large", cannot be enabled
  2. parameter hint parsed from the filename  -> shown to admins, warning only
  3. RAM measured on first load (worker hook) -> status "over_ram", auto-disabled
The worker also refuses a load when free RAM is below the estimate + MIN_FREE_RAM_MB
(temporary, the model stays enabled).
"""

import logging
import re
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import utcnow
from app.engine.templates import FAMILIES, guess_family
from app.engine.worker import ModelSpec
from app.models import LLMModel

log = logging.getLogger(__name__)

PARAM_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z])")
SAMPLING_KEYS = {"temperature", "top_p", "top_k", "repeat_penalty", "frequency_penalty", "presence_penalty"}


def param_hint(filename: str) -> float | None:
    m = PARAM_RE.search(Path(filename).stem)
    return float(m.group(1)) if m else None


def pretty_name(filename: str) -> str:
    stem = Path(filename).stem
    # cut at the first conversion marker: -rk3588, -w8a8, -opt-1, -hybrid-ratio...
    stem = re.sub(r"[-_](rk35\d\d|w\d+a\d+|opt[-_]|hybrid).*$", "", stem, flags=re.I)
    return stem.replace("_", " ").replace("-", " ").strip()[:128] or Path(filename).stem


def load_overrides(models_dir: Path) -> dict[str, dict]:
    path = models_dir / "models.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        models = data.get("models", data)
        return {str(k): (v or {}) for k, v in models.items()} if isinstance(models, dict) else {}
    except Exception:
        log.exception("could not parse %s", path)
        return {}


def file_status(size: int, settings: Settings) -> tuple[str, str | None]:
    cap = int(settings.max_model_file_gb * 1e9)  # decimal GB, same as the admin UI
    if size > cap:
        return "too_large", (
            f"File is {size / 1e9:.2f} GB, above the {settings.max_model_file_gb} GB cap "
            f"(≈{settings.max_param_hint_b:g}B parameters at w8a8)"
        )
    return "ok", None


async def scan_models(session: AsyncSession, settings: Settings) -> dict:
    models_dir = Path(settings.models_dir)
    found: dict[str, Path] = {}
    if models_dir.is_dir():
        for p in sorted(models_dir.rglob("*.rkllm")):
            found[p.relative_to(models_dir).as_posix()] = p
    else:
        log.warning("models dir %s does not exist", models_dir)

    overrides = load_overrides(models_dir)
    rows = {m.filename: m for m in (await session.execute(select(LLMModel))).scalars()}
    added = updated = missing = 0
    now = utcnow()

    for rel, path in found.items():
        st = path.stat()
        status, detail = file_status(st.st_size, settings)
        row = rows.get(rel)
        tok = path.with_suffix(".tokenizer.json")
        tokenizer_path = tok.relative_to(models_dir).as_posix() if tok.is_file() else None
        if row is None:
            ov = overrides.get(rel) or overrides.get(path.name) or {}
            family = ov.get("family") if ov.get("family") in FAMILIES else guess_family(rel)
            row = LLMModel(
                filename=rel,
                display_name=str(ov.get("display_name") or pretty_name(rel))[:128],
                family=family,
                max_context_len=int(ov.get("max_context_len") or settings.default_max_context),
                max_new_tokens=int(ov.get("max_new_tokens") or settings.default_max_new_tokens),
                sampling={k: v for k, v in (ov.get("sampling") or {}).items() if k in SAMPLING_KEYS},
                enabled=bool(ov.get("enabled", False)) and status == "ok",
                sort_order=int(ov.get("sort_order", 100)),
                status=status,
                status_detail=detail,
                file_size=st.st_size,
                file_mtime=st.st_mtime,
                param_hint_b=param_hint(rel),
                tokenizer_path=tokenizer_path or ov.get("tokenizer"),
                scanned_at=now,
            )
            session.add(row)
            added += 1
            continue

        changed_file = row.file_size != st.st_size or abs(row.file_mtime - st.st_mtime) > 1
        row.scanned_at = now
        if tokenizer_path:
            row.tokenizer_path = tokenizer_path
        if row.status == "over_ram" and not changed_file:
            continue  # sticky until the file changes or an admin resets it
        if changed_file:
            row.measured_ram_mb = None
        row.file_size, row.file_mtime = st.st_size, st.st_mtime
        row.param_hint_b = param_hint(rel)
        row.status, row.status_detail = status, detail
        if status != "ok":
            row.enabled = False
            row.keep_loaded = False
        updated += 1

    for rel, row in rows.items():
        if rel not in found and row.status != "missing":
            row.status, row.status_detail = "missing", "File no longer present in the models folder"
            row.enabled = False
            row.keep_loaded = False
            missing += 1

    await session.commit()
    log.info("model scan: %d added, %d updated, %d missing", added, updated, missing)
    return {"added": added, "updated": updated, "missing": missing, "total": len(found)}


def to_spec(row: LLMModel, settings: Settings) -> ModelSpec:
    return ModelSpec(
        id=row.id,
        path=str(Path(settings.models_dir) / row.filename),
        display_name=row.display_name,
        family=row.family,
        max_context_len=row.max_context_len,
        max_new_tokens=row.max_new_tokens,
        sampling=dict(row.sampling or {}),
        keep_loaded=row.keep_loaded,
        est_ram_mb=estimate_ram_mb(row),
    )


def estimate_ram_mb_from(file_size: int, param_hint_b: float | None, max_context_len: int) -> int:
    """Rough RAM need before loading: weights ≈ file size, plus KV cache and runtime overhead.

    The KV cache grows with model size: ~0.06 MB/token at 1.5B, ~0.16 MB/token at 4B (fp16 K+V).
    Without a filename hint, w8a8 files are ~1.15 GB per billion parameters.
    """
    params_b = param_hint_b or file_size / 1.15e9
    kv = max_context_len * max(0.03, 0.04 * params_b)
    return int(file_size / 1024**2 * 1.08 + kv + 150)


def estimate_ram_mb(row: LLMModel) -> int:
    return estimate_ram_mb_from(row.file_size, row.param_hint_b, row.max_context_len)
