"""Decision 69 D: a cached answer is only reused for the same thinking level."""

import hashlib
import json

from app import llm
from scripts.build_cache import BuildCache

VARS = {"questions": "q1"}


def _old_key(task: str) -> str:
    """The key as computed before decision 69: task, prompt version, prompt vars."""
    parts = (task, llm.load_prompt(task).version, json.dumps(VARS, sort_keys=True))
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def test_with_no_effort_set_the_key_is_unchanged(tmp_path, settings):
    cache = BuildCache(tmp_path, settings)
    assert cache._llm_key("link_confirm", VARS) == _old_key("link_confirm")


def test_a_different_effort_is_a_different_key(tmp_path, settings):
    low = settings.model_copy(update={"llm_reasoning_effort": {"link_confirm": "low"}})
    high = settings.model_copy(update={"llm_reasoning_effort": {"link_confirm": "high"}})
    k_default = BuildCache(tmp_path, settings)._llm_key("link_confirm", VARS)
    k_low = BuildCache(tmp_path, low)._llm_key("link_confirm", VARS)
    k_high = BuildCache(tmp_path, high)._llm_key("link_confirm", VARS)
    assert len({k_default, k_low, k_high}) == 3
    assert BuildCache(tmp_path, low)._llm_key("link_confirm", VARS) == k_low  # stable
    # another task's key ignores link_confirm's override
    assert BuildCache(tmp_path, low)._llm_key("link_merge", VARS) == _old_key("link_merge")
