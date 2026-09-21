import json
from unittest.mock import patch

import scripts.execution_gateway as gateway


def test_generate_sends_limits_and_disables_thinking():
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return b'{"response":"ok"}'

    with patch.object(gateway.urllib.request, "urlopen", return_value=Response()) as send:
        result = gateway._ollama_generate("http://127.0.0.1:11434", "qwen3:1.7b", "Hello", "30m",
                                         num_ctx=4096, num_predict=512, think=False)
    payload = json.loads(send.call_args.args[0].data)
    assert result["response"] == "ok"
    assert payload["options"] == {"num_ctx": 4096, "num_predict": 512}
    assert payload["think"] is False


def test_context_is_sent_to_model_and_never_semantic_cached():
    gateway._redis_client = None
    with patch.object(gateway, "_ollama_tags", return_value=["qwen3:1.7b"]), \
         patch.object(gateway, "_ollama_generate", return_value={"response": "ok"}) as generate, \
         patch.object(gateway.semantic_cache, "lookup") as lookup, \
         patch.object(gateway.semantic_cache, "store") as store:
        result = gateway.execute("Summarize it", context="Alpha document")
    assert result["decision"] == "inference"
    assert "Alpha document" in generate.call_args.args[2]
    lookup.assert_not_called()
    store.assert_not_called()
