from pathlib import Path

from packages.llm import PromptRegistry


def test_prompt_registry_renders_and_versions(tmp_path: Path):
    (tmp_path / "hello.md").write_text(
        '---\nversion: "3"\n---\n# SYSTEM\nYou are {{ role }}.\n# USER\nGoal: {{ goal }}\n'
    )
    reg = PromptRegistry(tmp_path)
    r = reg.render("hello", {"role": "coach", "goal": "run 5k"})
    assert r.version == "3"
    assert r.system == "You are coach."
    assert r.user == "Goal: run 5k"
    assert reg.version("hello") == "3"


def test_bundled_smoke_prompt_renders():
    reg = PromptRegistry(Path(__file__).resolve().parents[4] / "packages" / "llm" / "prompts")
    r = reg.render("smoke", {"goal": "run 5k"})
    assert "run 5k" in r.user
    assert r.system
