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

## Ollama Cloud mode (no download)

Paste the key into `OLLAMA_API_KEY.txt` in the ClaimComposer folder (the launcher then uses the cloud without asking),
set `source = "cloud"` in `config.toml`, or switch in Settings > AI.
Calls go to `https://ollama.com/api/chat` with `Authorization: Bearer <key>`; the URL is fixed in code so the key can
only ever be sent to Ollama Cloud. The key comes from the `OLLAMA_API_KEY` environment variable, `OLLAMA_API_KEY.txt`, or a key saved in Settings
(`userdata/ollama_api_key.txt`, permissions 600), and it is never returned by the API, written to `settings.json`, exported
or included in a release zip.

**Default cloud model: `gpt-oss:20b`.** Checked against the live Ollama Cloud model list on 21 November 2026: the
list contained `gpt-oss:20b` and `gpt-oss:120b`, but not `qwen3.5:4b`, so the local default is not used in the
cloud. The chat and JSON Schema test could not be completed: the account used for the check answered every chat
call with `402 Payment Required` ("Add usage credits or subscribe"). The app handles this case: it shows the
reason, stops calling the AI for that ticket and returns the template results. Once the account has credits,
`uv run python -m app.cli verify-model` runs the JSON Schema test.

### Automatic choice of the cloud model (`cloud_model = "auto"`, the default)

The cloud model is chosen from the models the API key can use, by fit for this app (short rewrites, German
translation, strict JSON, speed). `app/model_pick.py` ranks them:

| Rank | Models | Why |
|---|---|---|
| 1 | Qwen (not coder or vision) | Instruction following, strong German, reliable JSON; preferred by the project |
| 2 | Mistral | Very good German, reliable JSON |
| 3 | Gemma | Multilingual, mid-size |
| 4 | `gpt-oss:20b` | Small general model with dependable JSON |
| 5 | "flash" variants | Fast general models |
| 6 | Other large general models | Work, but slower than one sentence needs |
| – | Code, vision, OCR, embedding models | Excluded |

Smaller models win ties. At setup, `python -m app.cli pick-cloud-model` runs the JSON Schema test on the best-ranked
models in order and saves the first that passes. If the account itself is the problem (no credits, rejected key,
usage limit) it stops after one request and keeps the best-ranked model for later. At runtime, "auto" without a saved
choice resolves to the best-ranked model in the key's list.

With the key used for testing (21 November 2026) the list held no Qwen model, so the ranking starts with
`mistral-large-4`, then `gemma4:31b`, then `gpt-oss:20b`. A Qwen model is chosen automatically as soon as the key
offers one. To force a model, set it in Settings > AI or `cloud_model` in `config.toml`.
