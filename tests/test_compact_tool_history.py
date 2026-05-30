"""Tests for compact_tool_history() stale checkpoint deduplication.

The fix (deployed in commit f37de0d) ensures that compact_tool_history()
never accumulates multiple identical [CHECKPOINT ...] system messages.
Only the LAST checkpoint survives; all earlier ones are dropped during
compaction.

Run: python -m pytest tests/test_compact_tool_history.py -v
"""
import sys
import pathlib

import pytest

# Make sure repo root is on path
REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ouro.context import compact_tool_history


# ── Helpers ──────────────────────────────────────────────────────


def _make_tool_round(tool_id: str = "t1", result: str = "ok") -> list:
    """Build a minimal valid tool-call round (assistant + tool messages)."""
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tool_id,
                    "type": "function",
                    "function": {"name": "foo", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": tool_id,
            "content": result,
        },
    ]


def _make_checkpoint(text: str = "[CHECKPOINT round=50] Self-check reminder") -> dict:
    """Build a checkpoint system message."""
    return {"role": "system", "content": text}


def _make_tool_rounds(n: int, prefix: str = "t") -> list:
    """Build n tool rounds with unique IDs."""
    msgs = []
    for i in range(n):
        msgs.extend(_make_tool_round(f"{prefix}{i}", f"result-{i}"))
    return msgs


def _count_checkpoints(messages: list) -> int:
    """Count checkpoint system messages in a list."""
    return sum(
        1
        for m in messages
        if m.get("role") == "system"
        and isinstance(m.get("content"), str)
        and "[CHECKPOINT" in m["content"]
    )


# ── Tests ────────────────────────────────────────────────────────


def test_dedup_keeps_only_last_checkpoint():
    """Multiple checkpoint messages are deduped — only the last survives."""
    # 10 tool rounds (> default keep_recent=6), interleaved with 3 checkpoints
    rounds = _make_tool_rounds(10)
    checkpoint_a = _make_checkpoint("[CHECKPOINT round=50] first")
    checkpoint_b = _make_checkpoint("[CHECKPOINT round=100] second")
    checkpoint_c = _make_checkpoint("[CHECKPOINT round=150] third")

    messages = (
        rounds[:4]          # first 4 tool msgs (2 rounds)
        + [checkpoint_a]
        + rounds[4:8]       # next 4 (2 rounds)
        + [checkpoint_b]
        + rounds[8:]        # final 4 (2 rounds)
        + [checkpoint_c]
    )

    result = compact_tool_history(messages, keep_recent=6)

    checkpoint_msgs = [
        m for m in result
        if m.get("role") == "system"
        and isinstance(m.get("content"), str)
        and "[CHECKPOINT" in m["content"]
    ]

    assert len(checkpoint_msgs) == 1, (
        f"Expected 1 checkpoint in output, got {len(checkpoint_msgs)}: {checkpoint_msgs}"
    )
    assert checkpoint_msgs[0]["content"] == "[CHECKPOINT round=150] third", (
        "Kept wrong checkpoint — should be the last one"
    )


def test_dedup_multiple_checkpoints_different_content():
    """Dedup works regardless of checkpoint content variation."""
    rounds = _make_tool_rounds(8)
    checkpoints = [
        _make_checkpoint(f"[CHECKPOINT round={r}] reminder #{i}")
        for i, r in enumerate([10, 20, 30])
    ]

    # Scatter checkpoints through the message list
    messages = (
        [checkpoints[0]]
        + rounds[:4]
        + [checkpoints[1]]
        + rounds[4:]
        + [checkpoints[2]]
    )

    result = compact_tool_history(messages, keep_recent=6)

    assert _count_checkpoints(result) == 1, (
        "Only the last checkpoint should survive deduplication"
    )
    # The last checkpoint must be the one that survived
    surviving = [m for m in result if "[CHECKPOINT" in str(m.get("content", ""))]
    assert surviving[0]["content"] == checkpoints[2]["content"]


def test_no_checkpoint_unaffected():
    """Messages without checkpoints compact normally — no errors."""
    rounds = _make_tool_rounds(10)
    messages = [
        {"role": "system", "content": "You are Ouro."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ] + rounds

    result = compact_tool_history(messages, keep_recent=6)

    # No checkpoint messages added or removed
    assert _count_checkpoints(result) == 0
    # The system/user/assistant messages are preserved
    roles = [m["role"] for m in result]
    assert roles[0] == "system"
    assert roles[1] == "user"


def test_single_checkpoint_preserved():
    """A single checkpoint message is never dropped."""
    rounds = _make_tool_rounds(10)
    checkpoint = _make_checkpoint("[CHECKPOINT round=50] only one")
    messages = rounds[:6] + [checkpoint] + rounds[6:]

    result = compact_tool_history(messages, keep_recent=6)

    assert _count_checkpoints(result) == 1, (
        "The single checkpoint must be preserved, not dropped"
    )


def test_checkpoint_dedup_requires_compaction_to_trigger():
    """Dedup only fires when actual compaction is triggered (rounds > keep_recent).

    The early-return path (`return messages`) skips the dedup loop entirely.
    So with fewer tool rounds than keep_recent, duplicate checkpoints are
    returned as-is — this is acceptable since compaction is the trigger.
    """
    # Only 3 rounds (< keep_recent=6), 2 checkpoints
    rounds = _make_tool_rounds(3)
    cp1 = _make_checkpoint("[CHECKPOINT round=10] early")
    cp2 = _make_checkpoint("[CHECKPOINT round=20] late")

    messages = [cp1] + rounds + [cp2]
    result = compact_tool_history(messages, keep_recent=6)

    # Early return fires — messages returned unchanged, both checkpoints present
    assert result == messages, "Messages should be returned unchanged (no compaction)"
    assert _count_checkpoints(result) == 2, (
        "Without compaction the dedup loop does not run — both checkpoints present"
    )

    # NOW trigger compaction: same checkpoints, but enough rounds
    rounds_enough = _make_tool_rounds(8)
    messages2 = [cp1] + rounds_enough + [cp2]
    result2 = compact_tool_history(messages2, keep_recent=6)

    assert _count_checkpoints(result2) == 1, (
        "With compaction triggered, only the last checkpoint should survive"
    )


def test_non_checkpoint_system_messages_preserved():
    """System messages without [CHECKPOINT are never dropped."""
    rounds = _make_tool_rounds(10)
    sys_prompt = {"role": "system", "content": "You are a helpful assistant."}
    knowledge_note = {"role": "system", "content": "User prefers brief answers."}
    checkpoint = _make_checkpoint()

    messages = [sys_prompt, knowledge_note, checkpoint] + rounds

    result = compact_tool_history(messages, keep_recent=6)

    # Both non-checkpoint system messages must survive
    system_contents = [m["content"] for m in result if m.get("role") == "system"]
    assert sys_prompt["content"] in system_contents, "System prompt was dropped"
    assert knowledge_note["content"] in system_contents, "Knowledge note was dropped"


def test_output_messages_count_reasonable():
    """After compaction the message count is strictly less than input count when checkpoints exist."""
    rounds = _make_tool_rounds(10)
    checkpoints = [_make_checkpoint(f"[CHECKPOINT round={i*50}]") for i in range(1, 5)]

    messages = []
    for i, cp in enumerate(checkpoints):
        messages.extend(rounds[i * 2 : i * 2 + 2])
        messages.append(cp)
    messages.extend(rounds[8:])  # last 2 rounds

    original_count = len(messages)
    result = compact_tool_history(messages, keep_recent=6)

    # 3 extra checkpoints should be removed
    assert len(result) < original_count, (
        "Compaction + dedup should produce fewer messages than input"
    )
    assert _count_checkpoints(result) == 1
