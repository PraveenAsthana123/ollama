import scripts.warm_models as warm_models


def test_default_models_derives_from_real_config_prewarm_flags():
    """Real regression test for a real bug: this module used to hardcode
    its own duplicate copy of the tier model list, which silently drifted
    from config/token-tower.yaml (the strong tier's prewarm:false was
    already correct in config, but nothing enforced the two staying in
    sync). Asserts against the real config file, not a mock."""
    models = warm_models._default_models()
    assert "qwen3:1.7b" in models
    assert "qwen2.5-coder:1.5b" in models
    assert "qwen2.5:latest" not in models  # strong tier: prewarm is deliberately false


def test_env_override_still_works():
    import importlib
    import os

    os.environ["OLLAMA_WARM_MODELS"] = "custom-model:1b,another-model:2b"
    try:
        importlib.reload(warm_models)
        assert warm_models.MODELS == ["custom-model:1b", "another-model:2b"]
    finally:
        del os.environ["OLLAMA_WARM_MODELS"]
        importlib.reload(warm_models)  # restore real config-derived state for other tests
