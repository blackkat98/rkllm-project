from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class LoadParams:
    model_path: str
    max_context_len: int = 4096
    max_new_tokens: int = 2048
    temperature: float = 0.8
    top_p: float = 0.9
    top_k: int = 20
    repeat_penalty: float = 1.1
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    cpu_mask: int = 0
    cpu_num: int = 4

    @classmethod
    def from_sampling(cls, model_path: str, max_context_len: int, max_new_tokens: int, sampling: dict, **kw):
        allowed = {"temperature", "top_p", "top_k", "repeat_penalty", "frequency_penalty", "presence_penalty"}
        return cls(
            model_path=model_path,
            max_context_len=max_context_len,
            max_new_tokens=max_new_tokens,
            **{k: v for k, v in (sampling or {}).items() if k in allowed},
            **kw,
        )


@dataclass
class GenResult:
    tokens: int = 0
    aborted: bool = False
    error: str | None = None
    extra: dict = field(default_factory=dict)


TokenSink = Callable[[str], None]


class Backend:
    """Blocking inference backend. All methods are called from the single worker thread,
    except abort(), which may be called from any thread."""

    def load(self, params: LoadParams) -> None:
        raise NotImplementedError

    def unload(self) -> None:
        raise NotImplementedError

    def generate(self, prompt: str, keep_history: bool, on_token: TokenSink, hint: str = "chat") -> GenResult:
        raise NotImplementedError

    def abort(self) -> None:
        raise NotImplementedError

    def clear_kv(self) -> None:
        raise NotImplementedError

    @property
    def loaded(self) -> bool:
        raise NotImplementedError
