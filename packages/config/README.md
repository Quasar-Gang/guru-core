# packages/config

Loading the YAML in `config/`, with environment expansion.

## What it owns

`load_yaml_config(path, Model)` reads a file, expands `${VAR:-default}` against the
environment, and validates the result into a Pydantic model. `CONFIG_DIR` points at the
repository's `config/`.

Expanding the environment inside the file is what lets one YAML describe every deployment:
`config/llm.yaml` is the same file on a laptop and in production, and switching provider is
a change of environment rather than a change of code.

## Ports it exposes

None. It is a function and a path.

## What it does not do

It knows nothing about what any particular config means. The models live with the code that
reads them — `SchedulerConfig` in the Engine's domain, `TagVocabulary` in the Catalog's —
so a config file and the rules it feeds stay next to each other.
