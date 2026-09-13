# Verification against the live endpoint

Date: 2026-09-13
Machine: macOS, codex-cli 0.153.4, 9router on `http://127.0.0.1:20128/v1`

## 1. The endpoint answers

    curl -s -m 5 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:20128/v1/models
    200

## 2. The profile

    xsync setup

The command read 35 models from the endpoint and wrote
`~/.config/xsync/profiles.toml` with mode `-rw-------`.

    active = "9router"

    [profiles.9router]
    base_url = "http://127.0.0.1:20128/v1"
    wire_api = "responses"
    api_key = "<redacted>"

## 3. The difference

    xsync codex --dry-run

    + 8 added      cmc/deepseek/deepseek-v4.1-flash, ed3n/claude-haiku-4-5-20251001, …
    - 125 removed  tkr/openai/gpt-5.4-nano, tkr/google/gemini-3.5-flash-lite, … (+117)
    ~ 27 changed   cmc/MiniMaxAI/MiniMax-M2.5 (context_window, description, …)
      0 unchanged
    no files written (--dry-run)

The command wrote no file.

## 4. The write

    xsync codex
    wrote 35 models to /Users/robinx/.codex/9router-models.json

| Item | Before | After |
|---|---|---|
| Models | 152 | 35 |
| `tkr/` entries | 125 | 0 |
| File size | 4.5 MB | 1.0 MB |
| `cmc/deepseek/deepseek-v4.1-flash` | absent | present |

The backup `9router-models.json.bak` holds the 152-model file.

## 5. A defect that the comparison found

The first rules file held invented values. A comparison against the working
catalog found them:

| Field | Value that works | First value | Result |
|---|---|---|---|
| `effective_context_window_percent` | `95` | `1.0` | wrong scale |
| `truncation_policy` | `{"mode": "tokens", "limit": 10000}` | `"auto"` | wrong type |
| `model_messages` | an object with `instructions_template` | `[]` | the second prompt was lost |
| `default_reasoning_summary` | `"none"` | `"auto"` | wrong |
| `include_skills_usage_instructions` | `false` | `true` | wrong |
| `support_verbosity` | `true` | `false` | wrong |
| `supports_image_detail_original` | `true` | `false` | wrong |

The commit `6813a49` corrects every value. The extraction tool now also
copies the `model_messages` object. The models `cx/gpt-5.5` and `cx/gpt-5.4`
keep their speed tiers, their priority, and their verbosity.

## 6. The differences that stay

These differences are correct. The endpoint is the authority.

| Field | Models | Reason |
|---|---|---|
| `context_window`, `max_context_window` | 22 | The endpoint reports the true window. |
| `supports_search_tool`, `web_search_tool_type` | 12 | The old file claimed search for every model. |
| `input_modalities` | 10 | The old file claimed vision for every model. |
| `supported_reasoning_levels` | 3 | The endpoint reports the reasoning support. |
| `description` | 27 | The description is now the slug. |
| `priority` | 24 | The sort order is now a rule value. |

## 7. Open item

A person must confirm the result inside Codex. Run `/model` and check:

- The list holds 35 models.
- The list holds `cmc/deepseek/deepseek-v4.1-flash`.
- The list holds no `tkr/` model.
- A reasoning model offers low, medium, high, and xhigh.
- A request to one model succeeds.

The test suite holds 112 tests. Every test passes.
