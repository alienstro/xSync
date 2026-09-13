# xsync-cli

Sync the model list of an OpenAI-compatible endpoint into the Codex model
catalog.

Codex reads its model list from a large JSON catalog file. A person must
write that file by hand. The file becomes wrong when the endpoint adds a
model or drops a model. `xsync` writes the file for you.

    xsync codex
    wrote 35 models to /Users/you/.codex/9router-models.json

## Install

    uv tool install xsync-cli

Or:

    pipx install xsync-cli

The package needs Python 3.11 or later. The command is `xsync`.

## Start

### 1. Make a profile

    xsync setup

The command asks for the profile name, the base URL, and the API key. Leave
the key empty when the endpoint needs none. The command then reads the
endpoint and shows every model that it serves.

The last question asks for the wire API:

- `chat` — most OpenAI-compatible servers.
- `responses` — the OpenAI Responses API.

A wrong value breaks every request. Ask the operator of the endpoint when
you do not know.

### 2. Connect Codex to the endpoint

    xsync codex --init

The command adds `[model_providers.<profile>]` to `~/.codex/config.toml` and
points `model_catalog_json` at the catalog of the profile. Run this one time
for each endpoint.

### 3. Sync

    xsync codex

Run this command again when the endpoint changes.

## Commands

| Command | Action |
|---|---|
| `xsync setup` | Make a profile. |
| `xsync list` | Show the profiles. The active profile has a star. |
| `xsync use <name>` | Set the active profile. |
| `xsync remove <name>` | Delete a profile. |
| `xsync codex` | Sync the active profile into the Codex catalog. |
| `xsync codex --dry-run` | Show the difference. Write nothing. |
| `xsync codex --profile <name>` | Use another profile for one run. |
| `xsync codex --init` | Connect Codex to the endpoint of the profile. |
| `xsync codex --reset` | Remove everything that xSync wrote. |
| `xsync codex --reset --force` | Reset when no state file exists. |

Exit codes: `0` for success, `1` for an error, `2` when the endpoint does not
answer.

## Switch between endpoints

Codex holds one model provider. Therefore one profile is active at a time.

    xsync codex --profile openrouter --init

This command points Codex at the other endpoint and fills the catalog in one
step.

`xsync codex --profile X` without `--init` fills the catalog from X while
Codex still routes somewhere else. Every model then fails at request time.
xSync finds this mismatch before it writes, and it stops:

    catalog would come from "openrouter" (https://openrouter.ai/api/v1)
    but Codex routes to "9router" (http://127.0.0.1:20128/v1)
    run: xsync codex --profile openrouter --init

## The profile file

Path: `~/.config/xsync/profiles.toml`. Mode: `0600`.

    active = "9router"

    [profiles.9router]
    base_url = "http://127.0.0.1:20128/v1"
    api_key = "sk-..."
    wire_api = "responses"

    [profiles.openrouter]
    base_url = "https://openrouter.ai/api/v1"
    api_key_env = "OPENROUTER_API_KEY"
    wire_api = "chat"
    exclude = ["*-embedding-*"]

A profile uses `api_key` or `api_key_env`, but not both. Use `api_key_env`
when you share the file. A profile with neither key sends no `Authorization`
header.

The `include` and `exclude` lists hold glob patterns. An empty `include`
list keeps every model. The `exclude` list always wins.

## Safety

- The catalog write is atomic. xSync writes a temporary file, confirms the
  JSON, and then replaces the target. It keeps one backup with the suffix
  `.bak`.
- The everyday `xsync codex` command never opens `config.toml` for writing.
  Only `--init` and `--reset` do.
- Codex writes `config.toml` while it runs. Therefore `--init` and `--reset`
  hash the file before the edit and again before the replace. On a
  difference they stop and write nothing.
- `--reset` removes only what the state file `~/.codex/.xsync-state.json`
  records. It never restores an old copy of `config.toml`, because Codex
  adds project entries to that file over time.
- With no state file, `--reset` prints the keys that it would remove and
  then stops. Add `--force` to continue.
- xSync never prints an API key.

## What xSync reads and what it writes

| File | Read | Write |
|---|---|---|
| `{base_url}/models` | yes | no |
| `~/.config/xsync/profiles.toml` | yes | yes |
| `~/.codex/<profile>-models.json` | yes | yes |
| `~/.codex/config.toml` | yes | only with `--init` or `--reset` |
| `~/.codex/.xsync-state.json` | yes | only with `--init` or `--reset` |

## The catalog fields

The Codex catalog needs 33 fields for each model. The endpoint supplies
approximately 8 of them:

| Codex field | Source |
|---|---|
| `slug` | the model id |
| `context_window`, `max_context_window` | the context window |
| `input_modalities` | the vision flag |
| `supported_reasoning_levels` | the reasoning flag |
| `supports_parallel_tool_calls` | the tool flag |
| `supports_search_tool` | the search flag |

The other fields come from `adapters/rules/codex.toml`. The rules apply in
three layers. A later layer wins:

1. `[defaults]`
2. `[prefix.<first slug segment>]`
3. `[slug."<exact slug>"]`

Every default value comes from a catalog that works with codex-cli 0.153.4.

## Develop

    uv run --extra dev pytest

No test opens a network connection.

## License

MIT.
