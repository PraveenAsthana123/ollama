import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

import pytest

from portal import app


def test_operations_terminal_rejects_shell_syntax():
    assert "Unknown command" in app.terminal_command("status; rm -rf /")
    assert "Unknown command" in app.terminal_command("$(id)")


def test_prepare_task_routes_code_and_bounds_input():
    assert app.prepare_task("Write a function", "code", "direct") == ("Write a function", "source")
    with pytest.raises(ValueError):
        app.prepare_task("x" * 12001, "text", "direct")


def test_claude_preparation_feeds_local_model_prompt():
    class Completed:
        returncode = 0
        stdout = "Concise bounded task"

    with patch.object(app.subprocess, "run", return_value=Completed()) as run:
        prompt, kind = app.prepare_task("Build a summary", "job", "claude")
    assert prompt == "Concise bounded task"
    assert kind == "prose"
    assert run.call_args.args[0][0:2] == ["claude", "-p"]


def test_health_is_live_but_does_not_generate():
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    with patch.object(app.urllib.request, "urlopen", return_value=Response()) as get, \
         patch.object(app.socket, "create_connection"):
        status = app.health_status()
    assert status["ok"] is True
    assert get.call_count == 3
    assert all("/api/generate" not in call.args[0] for call in get.call_args_list)


def test_operations_post_requires_form_token():
    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/terminal"
    try:
        with urllib.request.urlopen(url) as response:
            page = response.read().decode()
        token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(url, data=b"command=help")
        assert denied.value.code == 403
        body = urllib.parse.urlencode({"csrf": token, "command": "help"}).encode()
        with urllib.request.urlopen(url, data=body) as allowed:
            assert "Available commands" in allowed.read().decode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
