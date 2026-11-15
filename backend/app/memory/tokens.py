"""Token estimation. Uses a model's tokenizer.json when present (accurate), otherwise a
conservative chars/token heuristic."""

import logging
import math
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


class TokenCounter:
    def __init__(self, chars_per_token: float = 3.0, tokenizer_file: str | None = None):
        self.chars_per_token = chars_per_token
        self._tok = _load_tokenizer(tokenizer_file) if tokenizer_file else None

    @property
    def exact(self) -> bool:
        return self._tok is not None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._tok is not None:
            try:
                return len(self._tok.encode(text, add_special_tokens=False).ids)
            except Exception:
                pass
        return math.ceil(len(text) / self.chars_per_token)

    def count_message(self, content: str) -> int:
        return self.count(content) + 6  # role markers / separators


@lru_cache(maxsize=8)
def _load_tokenizer(path: str):
    if not Path(path).is_file():
        return None
    try:
        from tokenizers import Tokenizer

        return Tokenizer.from_file(path)
    except Exception:
        log.warning("could not load tokenizer %s, falling back to heuristic", path)
        return None
