from app.engine.templates import Msg, get_template, guess_family, strip_think


def test_guess_family():
    assert guess_family("DeepSeek-R1-Distill-Qwen-1.5B_W8A8_RK3588.rkllm") == "deepseek"
    assert guess_family("Qwen2.5-1.5B-Instruct-rk3588-w8a8.rkllm") == "chatml"
    assert guess_family("gemma-3-1b-it-rk3588-w8a8-opt-1-hybrid-ratio-0.0.rkllm") == "gemma"
    assert guess_family("Llama-3.2-1B-Instruct_rk3588.rkllm") == "llama3"
    assert guess_family("TinyLlama-1.1B-chat.rkllm") == "llama2"
    assert guess_family("Phi-3-mini.rkllm") == "phi3"
    assert guess_family("something-else.rkllm") == "chatml"


def test_chatml_render_and_continuation():
    t = get_template("chatml")
    out = t.render("Be nice.", [Msg("user", "Hi"), Msg("assistant", "Hello!"), Msg("user", "Bye")])
    assert out == (
        "<|im_start|>system\nBe nice.<|im_end|>\n"
        "<|im_start|>user\nHi<|im_end|>\n"
        "<|im_start|>assistant\nHello!<|im_end|>\n"
        "<|im_start|>user\nBye<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
    assert t.continuation("Next") == "<|im_end|>\n<|im_start|>user\nNext<|im_end|>\n<|im_start|>assistant\n"


def test_gemma_merges_system_into_first_user_turn():
    out = get_template("gemma").render("SYS", [Msg("user", "Hi")])
    assert out == "<start_of_turn>user\nSYS\n\nHi<end_of_turn>\n<start_of_turn>model\n"


def test_deepseek_uses_real_special_tokens_and_strips_think():
    out = get_template("deepseek").render(None, [Msg("user", "Q"), Msg("assistant", "<think>x</think>A"), Msg("user", "Q2")])
    assert out.startswith("<｜begin▁of▁sentence｜>")  # U+2581, not a space
    assert "<think>" not in out
    assert out.endswith("<｜User｜>Q2<｜Assistant｜>")


def test_llama3_headers():
    out = get_template("llama3").render("S", [Msg("user", "Hi")])
    assert out == (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nS<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\nHi<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def test_strip_think_handles_unclosed_block():
    assert strip_think("<think>still thinking") == ""
    assert strip_think("<think>a</think>\nanswer") == "answer"
