# xSync Design

Date: 2026-09-13
Status: Approved for planning

## 1. Purpose

xSync syncs the model list of an OpenAI-compatible endpoint into the Codex
model catalog. The user runs one command. Codex then shows all of the models
in its `/model` picker, with the correct reasoning levels.

xSync replaces manual edits of a large JSON catalog file.

## 2. Problem

The user runs 9router on `http://127.0.0.1:20128/v1`. Codex reads a model
catalog from `~/.codex/9router-models.json`. A person made that file by hand.

The file is now wrong:

- The catalog holds 152 models. The endpoint serves 35 models.
- 125 entries use the `tkr/` prefix. The endpoint does not serve them. Codex
  shows these dead models, and each request to them fails.
- The active default model `cmc/deepseek/deepseek-v4.1-flash` is not in the
  catalog. The `/model` picker cannot show it.
- The file is 4.5 MB, because it repeats the same 12,948-character
  `base_instructions` value 152 times.

## 3. Scope

xSync v1 supports one target harness: Codex.

The code separates the source from the target. A second harness needs a new
file in `adapters/`. It does not need a refactor.

xSync v1 does not support:

- More than one endpoint in one Codex catalog. Codex holds one global
  `model_provider` value, and a catalog entry carries no provider field.
  Therefore one profile is active at a time.
- Other harnesses. Claude Code is out of scope until someone confirms its
  model registry format.

## 4. Concepts

### 4.1 Profile

A profile holds the connection data for one OpenAI-compatible endpoint:

- `base_url` (required)
- `api_key` (optional)
- `wire_api` (`chat` or `responses`)
- `include` and `exclude` glob rules (optional)

The user makes a profile with `xsync setup`. The user switches the active
profile with `xsync use <name>`.

### 4.2 Model

A `Model` object holds provider-neutral facts: the slug, the context window,
the maximum output, and the capability flags. The `sources/` package makes
`Model` objects. The `adapters/` package reads them.

### 4.3 Rules

The Codex catalog needs 33 fields for each model. The endpoint supplies
approximately 8 of them. The other fields control the behavior of Codex.

The rules file supplies these fields in three layers. A later layer
overwrites an earlier layer:

1. `[defaults]`
2. `[prefix.<prefix>]`
3. `[slug."<exact slug>"]`

## 5. Architecture

```
xsync/
  cli.py                     # argument parsing, command dispatch
  core/model.py              # the Model dataclass
  core/profiles.py           # profiles.toml read and write, mode 0600
  core/filters.py            # include and exclude glob rules
  core/atomic.py             # atomic write, validation, single backup
  sources/openai_compat.py   # GET {base_url}/models -> list[Model]
  adapters/codex.py          # Model -> Codex entry; init, reset, state file
  adapters/rules/codex.toml  # defaults, prefix rules, slug rules
  adapters/prompts/*.md      # base_instructions bodies
tests/
  fixtures/                  # recorded API responses, golden output files
```

Rules:

- `sources/` knows nothing about Codex.
- `adapters/` knows nothing about HTTP.
- `core/` knows nothing about either one.

## 6. Storage

### 6.1 Profile store

Path: `~/.config/xsync/profiles.toml`. Mode: 0600.

```toml
active = "9router"

[profiles.9router]
base_url = "http://127.0.0.1:20128/v1"
api_key = "sk-..."
wire_api = "responses"
include = []
exclude = ["*-embedding-*"]

[profiles.openrouter]
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
wire_api = "chat"
```

A profile uses `api_key` or `api_key_env`, but not both. A profile with
neither key sends no `Authorization` header.

The user already stores the same key as clear text in `config.toml`.
Therefore clear text in `profiles.toml` adds no new exposure. xSync never
writes a key to a log or to the terminal.

### 6.2 State file

Path: `~/.codex/.xsync-state.json`.

```json
{
  "version": 1,
  "codex": {
    "profile": "9router",
    "keys_written": ["model_catalog_json", "model_provider", "model"],
    "blocks_written": ["model_providers.9router"],
    "files_written": ["/Users/robinx/.codex/9router-models.json"],
    "config_sha256": "...",
    "written_at": "2026-09-13T00:00:00Z"
  }
}
```

`--init` writes this file. `--reset` reads it, removes only the recorded
items, then deletes the file.

`--reset` never restores a snapshot of `config.toml`. Codex writes that file
itself, and it holds more than 300 `[projects.*]` trust entries. A snapshot
restore deletes the entries that Codex added later.

## 7. Commands

| Command | Action | Writes |
|---|---|---|
| `xsync setup` | Makes a profile. Asks for name, URL, key, filters, wire API. | `profiles.toml` |
| `xsync list` | Shows the profiles. Marks the active profile. | nothing |
| `xsync use <name>` | Sets the active profile. | `profiles.toml` |
| `xsync remove <name>` | Deletes a profile. | `profiles.toml` |
| `xsync codex` | Syncs the active profile into the Codex catalog. | catalog file |
| `xsync codex --profile <name>` | Uses that profile for this run only. | catalog file |
| `xsync codex --dry-run` | Shows the difference. | nothing |
| `xsync codex --init` | Connects Codex to the profile endpoint. | `config.toml`, state file |
| `xsync codex --reset` | Removes everything that xSync wrote. | `config.toml`, deletes files |
| `xsync codex --reset --force` | Removes the known keys when no state file exists. | as above |

Exit codes: `0` for success, `1` for an error, `2` when the endpoint does not
answer.

## 8. Setup flow

1. Ask for the profile name.
2. Ask for the base URL.
3. Ask for the API key. An empty answer is correct. It means no header.
4. Send `GET {base_url}/models`. Stop here on a failure. Save nothing.
5. Show the models: the id, the context window, the tool support, and the
   reasoning support. The user reads this list. The user does not select from
   it.
6. Ask for the optional include and exclude globs. The default is none.
7. Ask for the wire API. The default is `chat`. The 9router endpoint needs
   `responses`. xSync asks, because a wrong value breaks every request.
8. Write the profile. Set mode 0600. Make it active if it is the first
   profile.

## 9. Sync flow

1. Load the active profile, or the profile from `--profile`.
2. Resolve the key: `api_key`, or the variable named by `api_key_env`, or
   none.
3. Send `GET {base_url}/models`. Use a 10-second timeout and 2 retries.
4. Make `Model` objects. Apply the include and exclude globs. Sort by slug.
5. Check the provider match. Compare the profile `base_url` against the
   active `[model_providers.*]` block in `config.toml`. Stop on a mismatch,
   unless the run uses `--dry-run`. A `--dry-run` run prints a warning and
   continues, because it writes nothing. See section 11.
6. Apply the rules layers to each model.
7. Compare against the current catalog file. Count the added, removed,
   changed, and unchanged models.
8. Stop here for `--dry-run`. Print the difference. Write nothing.
9. Write the catalog. See section 12.

## 10. Field mapping

| Codex field | Source |
|---|---|
| `slug` | `id` |
| `context_window` | `capabilities.contextWindow` |
| `max_context_window` | `capabilities.contextWindow` |
| `input_modalities` | `["text"]`, plus `"image"` when `vision` is true |
| `supported_reasoning_levels` | the standard four levels when `reasoning` is true, else empty |
| `default_reasoning_level` | `"medium"` when `reasoning` is true, else null |
| `supports_parallel_tool_calls` | `tools` |
| `supports_search_tool` | `search` |
| `web_search_tool_type` | from `search` |
| `display_name` | the last slug segment, in title case |
| all other fields | the rules layers |

The endpoint also reports `maxOutput` and `max_completion_tokens`. The Codex
catalog has no field for these values. Therefore xSync reads them but does
not write them.

The Codex source code is not available on this machine. Therefore the
semantics of approximately 15 catalog fields are unconfirmed. The default
values in `adapters/rules/codex.toml` come directly from the current working
catalog. Those values work with codex-cli 0.153.4 today. The implementation
must not invent a value for a field that it does not understand.

### 10.1 The three prompts

The current catalog holds 3 different `base_instructions` values:

| Length | Models | Rule |
|---|---|---|
| 12,948 | 150 | `[defaults]` |
| 21,459 | `cx/gpt-5.5` | `[slug."cx/gpt-5.5"]` |
| 14,731 | `cx/gpt-5.4` | `[slug."cx/gpt-5.4"]` |

A bootstrap step copies these 3 values into `adapters/prompts/`. The step
copies the text exactly. It does not rewrite the text.

## 11. The mismatch guard

`--profile` fills the catalog from one endpoint. `config.toml` can still
route to a different endpoint. Every model then fails at request time, and
the error looks like a broken model.

Therefore xSync compares the profile `base_url` against the active provider
block before it writes. On a mismatch, xSync stops, writes nothing, and
prints:

```
catalog would come from "openrouter" (https://openrouter.ai/api/v1)
but Codex routes to "9router" (http://127.0.0.1:20128/v1)
run: xsync codex --profile openrouter --init
```

`--dry-run` shows the mismatch as a warning. It does not stop, because it
writes nothing.

To switch endpoints, the user runs one command:

```
xsync codex --profile openrouter --init
```

## 12. Safety

### 12.1 Catalog write

xSync writes the catalog to a temporary file in the same directory. It parses
that file to confirm valid JSON. It then calls `os.replace()`. It keeps
exactly one backup, `<name>.bak`.

### 12.2 Configuration write

`--init` and `--reset` edit `config.toml`. The everyday `xsync codex` command
does not.

Codex writes `config.toml` itself while it runs. Therefore xSync hashes the
file before the edit, and hashes it again before `os.replace()`. On a
difference, xSync stops and writes nothing:

```
config.toml changed during the edit. Close Codex and try again.
```

xSync uses `tomlkit` for this edit. `tomlkit` keeps the structure and the
order of the file. The standard `tomllib` module reads TOML but does not
write it.

### 12.3 Reset without a state file

The user connected Codex to 9router by hand. No state file exists yet.

Therefore `--reset` with no state file does not guess. It prints the exact
keys and blocks that it would remove. It then stops. The user must add
`--force` to continue.

## 13. Dependencies

- `tomlkit` — the only runtime dependency.
- The standard library supplies the rest. Use `urllib.request` for HTTP. Do
  not add `requests`.
- Python 3.11 or later, for `tomllib`.

## 14. Testing

Use test-driven development. Write the test first.

Tests use recorded fixtures. No test opens a network connection.

Test cases:

1. Map each capability flag to the correct catalog field.
2. Apply the rules layers in the correct order.
3. Apply the include and exclude globs.
4. Report the difference correctly: added, removed, changed, unchanged.
5. Write nothing for `--dry-run`.
6. Write the catalog atomically. Keep exactly one backup.
7. Resolve the key from `api_key`, from `api_key_env`, and from neither.
8. Stop on a malformed API response.
9. Stop with exit code 2 when the endpoint does not answer.
10. Stop on a provider mismatch.
11. Stop when the hash of `config.toml` changes during an edit.
12. Stop on `--reset` with no state file and no `--force`.
13. Remove only the recorded items on `--reset`.

## 15. Expected first result

The first run on this machine gives:

- 35 models in the catalog, in place of 152.
- 125 dead `tkr/` entries removed.
- `cmc/deepseek/deepseek-v4.1-flash` visible in the `/model` picker.
- The catalog file smaller than 4.5 MB.

## 16. Open questions

1. Does Codex accept `model_catalog_json` inside a `[profiles.*]` block? The
   answer is unknown. The user chose the global catalog, so this question
   does not block the work.
2. Which `wire_api` value does each endpoint need? xSync asks the user. It
   does not detect the value.

## 17. Distribution

### 17.1 Names

The PyPI name `xsync` belongs to a different project. Therefore:

| Item | Value |
|---|---|
| PyPI distribution | `xsync-cli` |
| Import package | `xsync_cli` |
| Command | `xsync` |

The distribution name and the command name are independent. The user types
`xsync`.

### 17.2 Install

```
uv tool install xsync-cli
pipx install xsync-cli
```

Both tools make an isolated environment. Therefore the unrelated `xsync`
library cannot conflict with this command.

### 17.3 Package data

The files `adapters/rules/codex.toml` and `adapters/prompts/*.md` are package
data, not code. The build must include them. Without them, every install
fails at the first sync.

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/xsync_cli"]

[tool.hatch.build.targets.wheel.force-include]
"src/xsync_cli/adapters/rules" = "xsync_cli/adapters/rules"
"src/xsync_cli/adapters/prompts" = "xsync_cli/adapters/prompts"
```

The code reads these files with `importlib.resources`. It does not use
`__file__` paths. A `__file__` path breaks in a zip install.

A test must confirm that a built wheel contains both directories.

### 17.4 Project metadata

```toml
[project]
name = "xsync-cli"
requires-python = ">=3.11"
dependencies = ["tomlkit>=0.13"]

[project.scripts]
xsync = "xsync_cli.cli:main"
```

### 17.5 Release steps

1. Run the full test suite. All tests pass.
2. Run `xsync codex --dry-run` against the local 9router endpoint. Confirm
   the output.
3. Set the version in `pyproject.toml`.
4. Build: `uv build`.
5. Upload to TestPyPI. Install from TestPyPI into a clean environment. Run
   `xsync --help` and `xsync codex --dry-run`.
6. Upload to PyPI: `uv publish`.

Step 5 is mandatory. PyPI does not allow a second upload of the same version
number, even after a delete. A broken release stays broken.

### 17.6 Version policy

The first release is `0.1.0`. The tool writes to `config.toml` and deletes
files. Therefore the version stays below `1.0.0` until the field mapping
works against a second endpoint.

### 17.7 Credentials

The upload needs a PyPI API token. The token belongs to the user. The token
never enters the repository. The user supplies it through the environment
variable `UV_PUBLISH_TOKEN` or through `~/.pypirc`.

## 18. The Claude Code adapter

Date added: 2026-09-13

### 18.1 What Claude Code offers

Claude Code holds no catalog file like Codex. It reads two things from
`~/.claude/settings.json`:

| Key | Purpose |
|---|---|
| `modelPicker.options` | The rows of the `/model` picker, in order. |
| `modelPicker.replaceBuiltInOptions` | True hides the built-in models. |
| `env` | The variables that point Claude Code at an endpoint. |

One picker row holds these fields:

| Field | Meaning |
|---|---|
| `model` | The model id, taken word for word. |
| `label` | The row title. |
| `description` | The row subtitle. |
| `behavesAs` | The id of a model that this version knows. Its prompt profile, its capability defaults, and its effort defaults then apply. |

Claude Code refuses a model that it does not know:

```
"cmc/deepseek/deepseek-v4-pro" isn't described by this version's model
catalog; update Claude Code, or map it with behavesAs on a modelPicker row
```

A model name that holds a known model id, such as
`ed3n/claude-sonnet-5`, needs no `behavesAs`.

### 18.2 The proof

Each fact below comes from a test on this machine, not from a document.

1. 9router answers the Anthropic API at `POST /v1/messages`.
2. `claude -p "say ok" --model ed3n/claude-sonnet-5` answered `ok`.
3. The same command with `cmc/deepseek/deepseek-v4-pro` failed, until a
   picker row gave it `behavesAs = "claude-opus-4-8"`. It then answered
   `ok`.
4. The variables in the `env` block of `settings.json` are enough. The
   shell needs no variable.

### 18.3 The design

- `xsync claude` writes `modelPicker.options` into `settings.json`.
- `replaceBuiltInOptions` stays `false`. The built-in models stay in the
  picker. The router models come after them. A router that stops
  therefore leaves a working picker.
- A rules file `adapters/rules/claude.toml` gives `behavesAs`. It uses
  the same layers as the Codex rules: defaults, prefix, name, slug.
- A model whose name holds a known Claude model id gets no `behavesAs`.
  It keeps its native handling.
- `xsync claude --init` writes the `env` block with
  `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN`.
- `xsync claude --reset` removes only what the state file records.

### 18.4 Safety

The file `settings.json` holds the hooks and the settings of the user. It
is large. Therefore:

- xSync changes the key `modelPicker` only, and the key `env` only with
  `--init`.
- The write is atomic. xSync keeps one backup.
- xSync hashes the file before the edit and again before the replace. On
  a difference it stops.
- The state file `~/.claude/.xsync-state.json` records every change.
