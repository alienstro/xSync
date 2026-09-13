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

### 2. Open a harness

    xsync codex
    xsync claude

The command builds a home for the profile, then starts the harness in that
home. The real Codex and the real Claude Code of the user stay as they are.

Arguments after `--` go to the harness:

    xsync claude -- --model cmc/deepseek/deepseek-v4-pro

### 3. Or write the real harness

    xsync codex apply
    xsync claude apply

The `apply` verb changes the real home of the user. Read **Safety** before
you use it.

## Commands

| Command | Action |
|---|---|
| `xsync setup` | Make a profile. |
| `xsync list` | Show the profiles. The active profile has a star. |
| `xsync use <name>` | Set the active profile. |
| `xsync remove <name>` | Delete a profile. |
| `xsync help` | Show the help. `xsync help codex` explains one command. |
| `xsync codex` | Open a Codex on the active profile, in its own home. |
| `xsync claude` | Open a Claude Code the same way. |
| `xsync codex -- <args>` | The arguments after `--` go to the harness. |
| `xsync codex apply` | Write the real Codex of the user. |
| `xsync claude apply` | Write the real Claude Code of the user. |
| `xsync <harness> apply --dry-run` | Show the difference. Write nothing. |
| `xsync <harness> apply --reset` | Remove everything that xSync wrote. |
| `xsync <harness> apply --reset --force --yes` | Reset with no question. |
| `xsync <harness> --profile <name>` | Use another profile for one run. |

## The isolated home

`xsync codex` and `xsync claude` do not change the settings of the user. Each
one builds a home under `~/.config/xsync/homes/<profile>/`, and then starts
the harness with `CODEX_HOME` or with `CLAUDE_CONFIG_DIR` set to that home.

The home starts as a copy of the real settings file, so the hooks of the
user and the trusted projects of the user stay. xSync then points the copy at
the endpoint of the profile.

The home shares the work of the user through a symbolic link:

| Harness | Shared |
|---|---|
| Codex | `skills`, `plugins`, `marketplaces`, `memories`, `AGENTS.md` |
| Claude Code | `agents`, `skills`, `plugins`, `hooks`, `commands`, `CLAUDE.md` |

A session, a cache, and a log stay inside the isolated home. They never mix
with the real home.

Delete a home at any time. The next command builds it again.

Exit codes: `0` for success, `1` for an error, `2` when the endpoint does not
answer.

## Claude Code

    xsync claude --init
    xsync claude

Claude Code holds no catalog file. It reads the rows of the `/model`
picker from `modelPicker.options` in `~/.claude/settings.json`, and it reads
the endpoint from the `env` block of the same file. `xsync claude` writes
those two keys and nothing else.

The endpoint must answer the Anthropic API at `POST /v1/messages`. An
endpoint that answers only the OpenAI API works with Codex, not with Claude
Code.

### The map to a known model

Claude Code refuses a model that it does not know:

    "cmc/deepseek/deepseek-v4-pro" isn't described by this version's model
    catalog; update Claude Code, or map it with behavesAs on a modelPicker row

Therefore each row carries `behavesAs`: the id of a model that Claude Code
knows. The prompt profile, the capability defaults, and the effort defaults
of that model then apply. The model id that Claude Code sends does not
change.

A model name that already holds a known model id, such as
`ed3n/claude-sonnet-5`, gets no `behavesAs`. It keeps its native handling.

Edit `adapters/rules/claude.toml` to change a map.

### The built-in models stay

xSync sets `replaceBuiltInOptions` to `false`. The built-in models stay at
the top of the picker, and the router models come after them. A router that
stops therefore leaves a working picker.

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

## The filters

A glob pattern selects a model by name. The sign `*` means any characters.

| Rule | Effect |
|---|---|
| `include = []` | Keep every model. This is the default. |
| `include = ["openai/*", "anthropic/*"]` | Keep only the models of those two providers. |
| `exclude = ["*embedding*"]` | Drop every model with `embedding` in the name. |
| `exclude = ["*-image-*", "*-tts-*"]` | Drop the image models and the speech models. |

The `exclude` list always wins over the `include` list. Use the filters when
an endpoint serves many models that you never choose in Codex.

The match ignores the letter case.

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
- `--reset` keeps the catalog backup `<name>.bak`. The backup is the only
  way back after a reset.
- With no state file, `--reset` prints the keys that it would remove and
  then stops. Add `--force` to continue. The command then asks a question
  before it removes anything. Add `--yes` to answer the question in a
  script.
- The setup hides the API key while you type it. It then shows the first
  five characters only, and it never shows the length of the key.
- xSync never prints a whole API key.

## The color

xSync writes color for a terminal. It writes plain text for a pipe, for a
dumb terminal, and when `NO_COLOR` holds a value. Set `FORCE_COLOR=1` to
keep the color in a pipe.

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
