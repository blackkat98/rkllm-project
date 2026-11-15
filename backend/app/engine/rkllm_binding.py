"""ctypes binding for librkllmrt.so v1.2.0 (RK3588 / RK3576).

Ported from rkllm_api_bundle/rkllm.py. Differences:
  * no module-level globals: the callback writes into the sink of the current run,
    so the state belongs to one RKLLMBackend instance;
  * incremental UTF-8 decoding (the original dropped split multi-byte sequences);
  * abort(), clear_kv() and set_chat_template() exposed, signatures checked against
    rknn-llm release-v1.2.0 include/rkllm.h:
        int rkllm_abort(LLMHandle handle);
        int rkllm_clear_kv_cache(LLMHandle handle, int keep_system_prompt);
        int rkllm_set_chat_template(LLMHandle, const char* system, const char* prefix, const char* postfix);
  * the runtime's built-in chat template is disabled so the backend controls the prompt.
"""

import codecs
import ctypes
import logging
import threading

from app.engine.base import Backend, GenResult, LoadParams, TokenSink

log = logging.getLogger(__name__)

RKLLM_Handle_t = ctypes.c_void_p

RKLLM_RUN_NORMAL = 0
RKLLM_RUN_WAITING = 1
RKLLM_RUN_FINISH = 2
RKLLM_RUN_ERROR = 3

RKLLM_INPUT_PROMPT = 0
RKLLM_INFER_GENERATE = 0


class RKLLMExtendParam(ctypes.Structure):
    _fields_ = [
        ("base_domain_id", ctypes.c_int32),
        ("embed_flash", ctypes.c_int8),
        ("enabled_cpus_num", ctypes.c_int8),
        ("enabled_cpus_mask", ctypes.c_uint32),
        ("reserved", ctypes.c_uint8 * 106),
    ]


class RKLLMParam(ctypes.Structure):
    _fields_ = [
        ("model_path", ctypes.c_char_p),
        ("max_context_len", ctypes.c_int32),
        ("max_new_tokens", ctypes.c_int32),
        ("top_k", ctypes.c_int32),
        ("n_keep", ctypes.c_int32),
        ("top_p", ctypes.c_float),
        ("temperature", ctypes.c_float),
        ("repeat_penalty", ctypes.c_float),
        ("frequency_penalty", ctypes.c_float),
        ("presence_penalty", ctypes.c_float),
        ("mirostat", ctypes.c_int32),
        ("mirostat_tau", ctypes.c_float),
        ("mirostat_eta", ctypes.c_float),
        ("skip_special_token", ctypes.c_bool),
        ("is_async", ctypes.c_bool),
        ("img_start", ctypes.c_char_p),
        ("img_end", ctypes.c_char_p),
        ("img_content", ctypes.c_char_p),
        ("extend_param", RKLLMExtendParam),
    ]


class RKLLMEmbedInput(ctypes.Structure):
    _fields_ = [("embed", ctypes.POINTER(ctypes.c_float)), ("n_tokens", ctypes.c_size_t)]


class RKLLMTokenInput(ctypes.Structure):
    _fields_ = [("input_ids", ctypes.POINTER(ctypes.c_int32)), ("n_tokens", ctypes.c_size_t)]


class RKLLMMultiModelInput(ctypes.Structure):
    _fields_ = [
        ("prompt", ctypes.c_char_p),
        ("image_embed", ctypes.POINTER(ctypes.c_float)),
        ("n_image_tokens", ctypes.c_size_t),
    ]


class RKLLMInputUnion(ctypes.Union):
    _fields_ = [
        ("prompt_input", ctypes.c_char_p),
        ("embed_input", RKLLMEmbedInput),
        ("token_input", RKLLMTokenInput),
        ("multimodal_input", RKLLMMultiModelInput),
    ]


class RKLLMInput(ctypes.Structure):
    _fields_ = [("input_mode", ctypes.c_int), ("input_data", RKLLMInputUnion)]


class RKLLMLoraParam(ctypes.Structure):
    _fields_ = [("lora_adapter_name", ctypes.c_char_p)]


class RKLLMPromptCacheParam(ctypes.Structure):
    _fields_ = [("save_prompt_cache", ctypes.c_int), ("prompt_cache_path", ctypes.c_char_p)]


class RKLLMInferParam(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("lora_params", ctypes.POINTER(RKLLMLoraParam)),
        ("prompt_cache_params", ctypes.POINTER(RKLLMPromptCacheParam)),
        ("keep_history", ctypes.c_int),
    ]


class RKLLMResultLastHiddenLayer(ctypes.Structure):
    _fields_ = [
        ("hidden_states", ctypes.POINTER(ctypes.c_float)),
        ("embd_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int),
    ]


class RKLLMResultLogits(ctypes.Structure):
    _fields_ = [
        ("logits", ctypes.POINTER(ctypes.c_float)),
        ("vocab_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int),
    ]


class RKLLMResult(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_char_p),
        ("token_id", ctypes.c_int),
        ("last_hidden_layer", RKLLMResultLastHiddenLayer),
        ("logits", RKLLMResultLogits),
    ]


CALLBACK_TYPE = ctypes.CFUNCTYPE(None, ctypes.POINTER(RKLLMResult), ctypes.c_void_p, ctypes.c_int)


class RKLLMBackend(Backend):
    def __init__(self, lib_path: str):
        self._lib = ctypes.CDLL(lib_path)
        self._setup_signatures()
        self._handle = RKLLM_Handle_t()
        self._is_loaded = False
        self._lock = threading.Lock()
        # per-run state, written by the C callback
        self._sink: TokenSink | None = None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._tokens = 0
        self._error = False
        self._aborted = False
        # keep a reference so the trampoline is not garbage-collected
        self._callback = CALLBACK_TYPE(self._on_result)

    def _setup_signatures(self) -> None:
        lib = self._lib
        lib.rkllm_init.argtypes = [ctypes.POINTER(RKLLM_Handle_t), ctypes.POINTER(RKLLMParam), CALLBACK_TYPE]
        lib.rkllm_init.restype = ctypes.c_int
        lib.rkllm_run.argtypes = [RKLLM_Handle_t, ctypes.POINTER(RKLLMInput), ctypes.POINTER(RKLLMInferParam), ctypes.c_void_p]
        lib.rkllm_run.restype = ctypes.c_int
        lib.rkllm_destroy.argtypes = [RKLLM_Handle_t]
        lib.rkllm_destroy.restype = ctypes.c_int
        lib.rkllm_abort.argtypes = [RKLLM_Handle_t]
        lib.rkllm_abort.restype = ctypes.c_int
        lib.rkllm_clear_kv_cache.argtypes = [RKLLM_Handle_t, ctypes.c_int]
        lib.rkllm_clear_kv_cache.restype = ctypes.c_int
        lib.rkllm_set_chat_template.argtypes = [RKLLM_Handle_t, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.rkllm_set_chat_template.restype = ctypes.c_int

    # --- C callback ---
    def _on_result(self, result, _userdata, state):
        try:
            if state == RKLLM_RUN_NORMAL:
                raw = result.contents.text
                if raw:
                    text = self._decoder.decode(raw)
                    self._tokens += 1
                    if text and self._sink:
                        self._sink(text)
            elif state == RKLLM_RUN_FINISH:
                tail = self._decoder.decode(b"", final=True)
                if tail and self._sink:
                    self._sink(tail)
            elif state == RKLLM_RUN_ERROR:
                self._error = True
        except Exception:  # never let an exception cross the C boundary
            log.exception("rkllm callback failed")

    @property
    def loaded(self) -> bool:
        return self._is_loaded

    def load(self, params: LoadParams) -> None:
        if self._is_loaded:
            self.unload()
        p = RKLLMParam()
        p.model_path = params.model_path.encode()
        p.max_context_len = params.max_context_len
        p.max_new_tokens = params.max_new_tokens
        p.skip_special_token = True
        p.n_keep = -1
        p.top_k = params.top_k
        p.top_p = params.top_p
        p.temperature = params.temperature
        p.repeat_penalty = params.repeat_penalty
        p.frequency_penalty = params.frequency_penalty
        p.presence_penalty = params.presence_penalty
        p.mirostat = 0
        p.mirostat_tau = 5.0
        p.mirostat_eta = 0.1
        p.is_async = False
        p.img_start = b""
        p.img_end = b""
        p.img_content = b""
        p.extend_param.base_domain_id = 0
        p.extend_param.embed_flash = 1
        p.extend_param.enabled_cpus_num = params.cpu_num
        p.extend_param.enabled_cpus_mask = params.cpu_mask

        self._handle = RKLLM_Handle_t()
        ret = self._lib.rkllm_init(ctypes.byref(self._handle), ctypes.byref(p), self._callback)
        if ret != 0:
            raise RuntimeError(f"rkllm_init failed with code {ret}")
        # disable the built-in template: prompts are fully rendered by app.engine.templates
        self._lib.rkllm_set_chat_template(self._handle, b"", b"", b"")
        self._is_loaded = True
        log.info("rkllm init ok: %s", params.model_path)

    def unload(self) -> None:
        if self._is_loaded:
            self._lib.rkllm_destroy(self._handle)
            self._is_loaded = False
            log.info("rkllm destroyed")

    def generate(self, prompt: str, keep_history: bool, on_token: TokenSink, hint: str = "chat") -> GenResult:
        if not self._is_loaded:
            return GenResult(error="model not loaded")
        self._sink = on_token
        self._decoder.reset()
        self._tokens = 0
        self._error = False
        self._aborted = False

        infer = RKLLMInferParam()
        ctypes.memset(ctypes.byref(infer), 0, ctypes.sizeof(RKLLMInferParam))
        infer.mode = RKLLM_INFER_GENERATE
        infer.keep_history = 1 if keep_history else 0

        inp = RKLLMInput()
        inp.input_mode = RKLLM_INPUT_PROMPT
        prompt_bytes = ctypes.c_char_p(prompt.encode("utf-8"))
        inp.input_data.prompt_input = prompt_bytes
        try:
            ret = self._lib.rkllm_run(self._handle, ctypes.byref(inp), ctypes.byref(infer), None)
        finally:
            self._sink = None
        if ret != 0 and not self._aborted:
            return GenResult(tokens=self._tokens, error=f"rkllm_run failed with code {ret}")
        if self._error and not self._aborted:
            return GenResult(tokens=self._tokens, error="rkllm runtime reported RKLLM_RUN_ERROR")
        return GenResult(tokens=self._tokens, aborted=self._aborted)

    def abort(self) -> None:
        if self._is_loaded:
            self._aborted = True
            self._lib.rkllm_abort(self._handle)

    def clear_kv(self) -> None:
        if self._is_loaded:
            self._lib.rkllm_clear_kv_cache(self._handle, 0)
