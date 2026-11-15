"""Fake engine so the whole stack runs on a dev machine without an NPU (RKLLM_ENGINE=mock)."""

import re
import threading
import time

from app.engine.base import Backend, GenResult, LoadParams, TokenSink

_REPLY = """Here's a mock reply from **{model}** (no NPU attached).

You said:

> {question}

Some markdown to exercise the renderer:

1. Ordered lists
2. `inline code`
3. And a code block:

```python
def hello(name: str) -> str:
    return f"Hello, {{name}}!"
```

| Turn | Prompt mode |
|------|-------------|
| this | {mode} |
"""


class MockBackend(Backend):
    def __init__(self, token_delay: float = 0.02, load_seconds: float = 1.0):
        self.token_delay = token_delay
        self.load_seconds = load_seconds
        self._params: LoadParams | None = None
        self._abort = threading.Event()
        self.kv_text = ""  # what a real runtime would hold in its KV cache
        self.history: list[dict] = []  # inspection hook for tests

    @property
    def loaded(self) -> bool:
        return self._params is not None

    def load(self, params: LoadParams) -> None:
        time.sleep(self.load_seconds)
        self._params = params
        self.kv_text = ""

    def unload(self) -> None:
        self._params = None
        self.kv_text = ""

    def abort(self) -> None:
        self._abort.set()

    def clear_kv(self) -> None:
        self.kv_text = ""

    def generate(self, prompt: str, keep_history: bool, on_token: TokenSink, hint: str = "chat") -> GenResult:
        if not self._params:
            return GenResult(error="model not loaded")
        self._abort.clear()
        self.history.append({"prompt": prompt, "keep_history": keep_history, "hint": hint})
        # the worker clears the cache before a full replay, so a non-empty cache means "continuation"
        incremental = keep_history and bool(self.kv_text)
        self.kv_text = (self.kv_text + prompt) if keep_history else ""

        model = self._params.model_path.rsplit("/", 1)[-1]
        if hint == "title":
            text = "Mock conversation title"
        elif hint == "summary":
            text = "Summary: the user and assistant discussed earlier topics (mock)."
        else:
            questions = re.findall(r"(?:user|User｜>)\n?(.*?)(?:<\||<end_of_turn>|<｜|$)", prompt, re.S)
            question = (questions[-1] if questions else prompt[-200:]).strip()[:300] or "…"
            mode = "incremental (KV cache)" if incremental else "full history replay"
            text = _REPLY.format(model=model, question=question.replace("\n", " "), mode=mode)
            if "deepseek" in model.lower() or "qwen3" in model.lower():  # exercise <think> rendering
                text = "<think>\nThe user wants a demo answer. Let me pretend to reason for a moment…\n</think>\n\n" + text

        tokens = 0
        for piece in re.findall(r"\s*\S+|\s+", text):
            if self._abort.is_set():
                return GenResult(tokens=tokens, aborted=True)
            on_token(piece)
            tokens += 1
            if self.token_delay:
                time.sleep(self.token_delay)
        if keep_history:
            self.kv_text += text
        return GenResult(tokens=tokens)
