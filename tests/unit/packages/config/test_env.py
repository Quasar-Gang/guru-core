import pytest

from packages.config.env import MissingEnvVar, expand_env


def test_expands_plain_var():
    assert expand_env("url: ${HOST}", {"HOST": "abc"}) == "url: abc"


def test_expands_default_when_missing():
    assert expand_env("k: ${NOPE:-fallback}", {}) == "k: fallback"


def test_env_wins_over_default():
    assert expand_env("k: ${A:-fallback}", {"A": "real"}) == "k: real"


def test_missing_without_default_raises():
    with pytest.raises(MissingEnvVar, match="HOST"):
        expand_env("url: ${HOST}", {})


def test_empty_default_allowed():
    assert expand_env("k: ${NOPE:-}", {}) == "k: "
