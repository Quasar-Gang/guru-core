from packages.llm import Purpose, load_llm_config


def test_load_llm_config_defaults(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "m1")
    cfg = load_llm_config()
    assert cfg.provider.adapter == "fake"
    assert cfg.provider.model == "m1"
    assert cfg.params_for(Purpose.generate).max_output_tokens == 4000
    assert cfg.budget_for(Purpose.recommend) == 600
    assert cfg.retry.max_attempts == 3
