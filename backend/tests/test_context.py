from app.memory.context import HistoryItem, compose_system, plan_context
from app.memory.summarizer import chunk_for_summary, clean_title, fallback_title
from app.memory.tokens import TokenCounter

C = TokenCounter(chars_per_token=1.0)  # 1 char == 1 token keeps the arithmetic obvious


def hist(n: int, size: int) -> list[HistoryItem]:
    return [HistoryItem(i + 1, "user" if i % 2 == 0 else "assistant", "x" * size) for i in range(n)]


def plan(history, **kw):
    args = dict(system_without_summary=[None, None, None], summary=None, history=history,
                max_context=1000, generation_reserve=100, counter=C, keep_recent=4)
    args.update(kw)
    return plan_context(**args)


def test_small_history_is_replayed_fully():
    p = plan(hist(4, 50))
    assert not p.to_fold
    assert len(p.messages) == 4
    assert not p.truncated


def test_large_history_requests_folding_of_oldest_turns_only():
    h = hist(12, 80)  # ~ 12*86 + 100 = 1132 > 700
    p = plan(h)
    assert p.to_fold
    assert p.to_fold[0].seq == 1
    folded = {i.seq for i in p.to_fold}
    assert not folded & {9, 10, 11, 12}  # latest keep_recent never folded
    assert p.to_fold[-1].role == "assistant"  # whole pairs


def test_after_summary_prompt_fits():
    h = hist(12, 80)
    first = plan(h)
    upto = first.to_fold[-1].seq
    p = plan([i for i in h if i.seq > upto], summary="short summary")
    assert not p.to_fold
    assert p.est_tokens <= 1000
    assert "short summary" in p.system


def test_no_fold_allowed_truncates_instead():
    p = plan(hist(12, 120), allow_fold=False)
    assert p.truncated
    assert p.est_tokens <= 1000


def test_single_huge_message_is_elided():
    p = plan([HistoryItem(1, "user", "y" * 5000)])
    assert p.truncated
    assert "[truncated]" in p.messages[0].content


def test_compose_system_order():
    s = compose_system("G", "CI", "CONV", "SUM")
    assert s.index("G") < s.index("CI") < s.index("CONV") < s.index("SUM")
    assert compose_system(None, None, None, None) is None


def test_chunking_and_titles():
    chunks = chunk_for_summary(hist(10, 100), 250, C)
    assert sum(len(c) for c in chunks) == 10 and all(chunks)
    assert clean_title('"Planning a trip."', "fb") == "Planning a trip"
    assert clean_title("<think>hmm</think>Title: Rust lifetimes", "fb") == "Rust lifetimes"
    assert clean_title("", "fallback") == "fallback"
    assert fallback_title("  how do I configure the NPU frequency governor on rk3588 boards  ").startswith("how do I")
