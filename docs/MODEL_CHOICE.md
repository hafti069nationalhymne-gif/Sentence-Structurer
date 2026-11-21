# Model choice

The local model has a narrow job: rewrite one short sentence in another tone, translate it into German, and write a
two-sentence explanation from supplied rule text. Every output is checked in code (numbers, placeholders, protected
phrases, new claim words, "Don't say", all sentence checks, cited `chunk_id`s) and discarded if it fails. The app is
complete without it. A small instruction-following model with JSON Schema output is therefore enough.

## Decision

| Hardware (detected by `python -m app.cli choose-model`) | Model |
|---|---|
| 16 GB of GPU memory, or 32 GB of RAM (also Apple silicon unified memory) | `gpt-oss:20b` |
| Anything less | `qwen3.5:4b` (default in `config.toml`) |

**Default: `qwen3.5:4b`.** Reasons: it is the smallest candidate in the brief, the task needs no long reasoning, and
it fits laptops with 8–16 GB of RAM, which is what focus-group participants are likely to bring. The larger
`gpt-oss:20b` is chosen automatically only where it runs comfortably; it is likely to translate more idiomatically.

The model stays changeable: `config.toml` (`chat_model`, `chat_model_large`) and the Settings panel (stored in
`userdata/settings.json`). Calls use `POST /api/chat` with `stream: false`, a JSON Schema in `format`,
`options: {temperature: 0, seed: 42}` and `think: false` (the client retries without `think` if a server rejects it).

## Verification status — please read

The brief asks to check that a model exists in the Ollama library and passes a JSON Schema test before pinning it.
**This could not be done in the build environment:** `ollama.com` and the Ollama registry were not reachable from it
(DNS failure), and there is no GPU. So neither tag was verified here, and no real model was run.

To make up for this, verification happens on the target computer, every time a model is set up:

1. The launcher pulls the chosen tag. If the tag does not exist in the library, the pull fails and the app switches to
   template mode with a one-line message.
2. `python -m app.cli verify-model <tag>` sends a JSON Schema request (`{"sentence": string, "count": integer}`)
   and checks the types of the answer. If it fails, the AI is switched off and template mode is used.

All AI code paths were tested against a fake Ollama server (`tests/fake_ollama.py`): accepted rewrites, rejected
rewrites (added number, changed number, dropped placeholder, added "sustainable", added certificate), one retry then
fallback, invalid citations, English "translations", Ollama missing and model missing.

If `qwen3.5:4b` turns out not to exist on the day of installation, set another small model with JSON Schema support
(for example a current Qwen or Llama tag) in Settings; the checks and fallbacks stay the same.
