
# Config Template

This directory contains the default configuration files. One of the configuration file, `conf.default.yaml` by default, will be copied to the root directory of this project as `conf.yaml`.

`mcp_servers.default.json` is copied to the project root as `mcp_servers.json` on first start when that file is missing. The runtime file is intentionally untracked because production deployments may store tokens in it; existing files are never overwritten.

`llm_models.example.yaml` documents the optional `llm_models.yaml`: the LLM models users may pick in the web UI, each optionally limited to specific accounts with `allowed_users`. It is never copied automatically; without `llm_models.yaml` in the project root every session uses its character's LLM.

Do not modify the content of these template unless you are contributing to this project.
