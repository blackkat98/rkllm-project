"""Prompt templates per model family.

Ported from rkllm_api_bundle/utils.py with fixes:
  * DeepSeek special tokens use U+2581 ("▁"), not a plain space.
  * Plain Qwen models use ChatML (the bundle wrongly routed them to the DeepSeek format;
    DeepSeek-R1-Distill-Qwen files contain "deepseek" in the name and still get DeepSeek).
  * Gemma has no system role -> system text is prepended to the first user turn.
  * Llama 3.x has its own header format (distinct from Llama 2 / Mistral [INST]).

The runtime's built-in template is disabled (rkllm_set_chat_template("", "", "")) so the
backend fully controls the prompt. That is what makes history replay (tier 1) and the
incremental "continuation" prompt for the KV-cache fast path (tier 3) possible.
"""

import re
from dataclasses import dataclass

THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.DOTALL)

FAMILIES = ["chatml", "deepseek", "gemma", "llama3", "llama2", "phi3"]


@dataclass
class Msg:
    role: str  # system | user | assistant
    content: str


def strip_think(text: str) -> str:
    return THINK_RE.sub("", text).strip()


def guess_family(filename: str) -> str:
    name = filename.lower()
    if "deepseek" in name:
        return "deepseek"
    if "qwen" in name or "chatml" in name or "smol" in name:
        return "chatml"
    if "gemma" in name:
        return "gemma"
    if re.search(r"llama[-_]?3", name):
        return "llama3"
    if "llama" in name or "mistral" in name or "tinyllama" in name:
        return "llama2"
    if "phi" in name:
        return "phi3"
    return "chatml"


class Template:
    def render(self, system: str | None, messages: list[Msg]) -> str:
        """Full prompt ending with the assistant generation prompt."""
        raise NotImplementedError

    def continuation(self, user_content: str) -> str:
        """Text appended to the KV cache after the previous assistant answer (tier-3 fast path).

        Begins by closing the previous assistant turn: the runtime stops at the EOS token,
        so whether that token is already in the cache is runtime-dependent. A duplicated
        end-of-turn marker is harmless, a missing one is not.
        """
        raise NotImplementedError


class ChatML(Template):
    def render(self, system, messages):
        out = ""
        if system:
            out += f"<|im_start|>system\n{system}<|im_end|>\n"
        for m in messages:
            out += f"<|im_start|>{m.role}\n{m.content}<|im_end|>\n"
        return out + "<|im_start|>assistant\n"

    def continuation(self, user_content):
        return f"<|im_end|>\n<|im_start|>user\n{user_content}<|im_end|>\n<|im_start|>assistant\n"


class DeepSeek(Template):
    BOS = "<｜begin▁of▁sentence｜>"
    EOS = "<｜end▁of▁sentence｜>"
    USER = "<｜User｜>"
    ASSISTANT = "<｜Assistant｜>"

    def render(self, system, messages):
        out = self.BOS + (system or "")
        for m in messages:
            if m.role == "user":
                out += self.USER + m.content
            elif m.role == "assistant":
                out += self.ASSISTANT + strip_think(m.content) + self.EOS
        return out + self.ASSISTANT

    def continuation(self, user_content):
        return self.EOS + self.USER + user_content + self.ASSISTANT


class Gemma(Template):
    def render(self, system, messages):
        out = ""
        pending_system = system
        for m in messages:
            if m.role == "user":
                content = m.content
                if pending_system:
                    content = f"{pending_system}\n\n{content}"
                    pending_system = None
                out += f"<start_of_turn>user\n{content}<end_of_turn>\n"
            elif m.role == "assistant":
                out += f"<start_of_turn>model\n{m.content}<end_of_turn>\n"
        return out + "<start_of_turn>model\n"

    def continuation(self, user_content):
        return f"<end_of_turn>\n<start_of_turn>user\n{user_content}<end_of_turn>\n<start_of_turn>model\n"


class Llama3(Template):
    def render(self, system, messages):
        out = "<|begin_of_text|>"
        if system:
            out += f"<|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>"
        for m in messages:
            out += f"<|start_header_id|>{m.role}<|end_header_id|>\n\n{m.content}<|eot_id|>"
        return out + "<|start_header_id|>assistant<|end_header_id|>\n\n"

    def continuation(self, user_content):
        return (
            f"<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{user_content}<|eot_id|>"
            "<|start_header_id|>assistant<|end_header_id|>\n\n"
        )


class Llama2(Template):
    def render(self, system, messages):
        out = ""
        sys_block = f"<<SYS>>\n{system}\n<</SYS>>\n\n" if system else ""
        first = True
        for m in messages:
            if m.role == "user":
                out += f"<s>[INST] {sys_block if first else ''}{m.content} [/INST]"
                first = False
            elif m.role == "assistant":
                out += f" {m.content} </s>"
        return out

    def continuation(self, user_content):
        return f" </s><s>[INST] {user_content} [/INST]"


class Phi3(Template):
    def render(self, system, messages):
        out = ""
        if system:
            out += f"<|system|>\n{system}<|end|>\n"
        for m in messages:
            out += f"<|{m.role}|>\n{m.content}<|end|>\n"
        return out + "<|assistant|>\n"

    def continuation(self, user_content):
        return f"<|end|>\n<|user|>\n{user_content}<|end|>\n<|assistant|>\n"


_TEMPLATES: dict[str, Template] = {
    "chatml": ChatML(),
    "deepseek": DeepSeek(),
    "gemma": Gemma(),
    "llama3": Llama3(),
    "llama2": Llama2(),
    "phi3": Phi3(),
}


def get_template(family: str) -> Template:
    return _TEMPLATES.get(family, _TEMPLATES["chatml"])
