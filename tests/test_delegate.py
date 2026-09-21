import json
from pathlib import Path
from unittest.mock import patch

import scripts.delegate as delegate


EVENTS = Path("/tmp/test_delegate_events.jsonl")


def setup_function():
    delegate.EVENTS_PATH = EVENTS
    if EVENTS.exists():
        EVENTS.unlink()


def test_delegate_logs_a_completed_task_and_returns_the_real_result():
    with patch.object(delegate.execution_gateway, "execute",
                       return_value={"decision": "inference", "model": "qwen3:1.7b", "response": "56"}):
        result = delegate.delegate("do some math", "What is 7 times 8?")

    assert result["response"] == "56"  # the real gateway result, unmodified
    events = [json.loads(line) for line in EVENTS.read_text().splitlines() if line.strip()]
    assert len(events) == 1
    assert events[0]["category"] == "task"
    assert events[0]["status"] == "completed"
    assert events[0]["name"] == "do some math"
    assert events[0]["model"] == "qwen3:1.7b"


def test_delegate_logs_a_blocked_task_with_its_reason():
    with patch.object(delegate.execution_gateway, "execute",
                       return_value={"decision": "blocked", "reason": "unauthorized"}):
        delegate.delegate("should fail", "irrelevant")

    events = [json.loads(line) for line in EVENTS.read_text().splitlines() if line.strip()]
    assert events[0]["status"] == "blocked"
    assert events[0]["reason"] == "unauthorized"


def test_delegate_logs_a_failed_task():
    with patch.object(delegate.execution_gateway, "execute",
                       return_value={"decision": "error", "reason": "TimeoutError: model timed out"}):
        delegate.delegate("should error", "irrelevant")

    events = [json.loads(line) for line in EVENTS.read_text().splitlines() if line.strip()]
    assert events[0]["status"] == "failed"


def test_report_returns_only_claude_delegate_task_events_newest_first():
    with patch.object(delegate.execution_gateway, "execute",
                       return_value={"decision": "inference", "model": "m1", "response": "a"}):
        delegate.delegate("first task", "q1")
    with patch.object(delegate.execution_gateway, "execute",
                       return_value={"decision": "inference", "model": "m2", "response": "b"}):
        delegate.delegate("second task", "q2")

    tasks = delegate.report(limit=10)
    assert [t["name"] for t in tasks] == ["second task", "first task"]  # newest first


def test_report_respects_limit():
    with patch.object(delegate.execution_gateway, "execute",
                       return_value={"decision": "inference", "model": "m", "response": "x"}):
        for i in range(5):
            delegate.delegate(f"task {i}", "q")

    assert len(delegate.report(limit=2)) == 2


def test_report_failed_only_filters_out_completed_tasks():
    with patch.object(delegate.execution_gateway, "execute",
                       return_value={"decision": "inference", "model": "m", "response": "ok"}):
        delegate.delegate("succeeds", "q")
    with patch.object(delegate.execution_gateway, "execute",
                       return_value={"decision": "blocked", "reason": "rate_limit_exceeded"}):
        delegate.delegate("gets blocked", "q")

    failed = delegate.report(limit=10, failed_only=True)
    assert len(failed) == 1
    assert failed[0]["name"] == "gets blocked"


def test_report_returns_empty_list_when_no_events_logged_yet():
    assert delegate.report() == []
