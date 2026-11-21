# ClaimComposer

ClaimComposer suggests environmental claims that fit EU and German rules. You answer a short questionnaire made of
choices, and it recommends 2 to 4 ready-made sentences. Each sentence comes with the regulations it rests on, why it
fits, the facts you must check first, and the phrases you should not use.

> Research prototype. Not legal advice. Human review required.

Everything runs on your own computer. There is no account or tracking, and after the first start it works offline,
unless you choose the optional Ollama Cloud mode described below.

## Start it

| Your computer | Double-click |
|---|---|
| Windows | `START_ClaimComposer.bat` |
| Mac | `START_ClaimComposer.command` (if macOS warns you, right-click it and choose *Open*) |
| Linux | `start_claimcomposer.sh` |

The first time, a window lists what it will download and asks once:

- **Install with AI**: also installs Ollama and a small language model (a few GB). The AI only rewrites the tone,
  translates and writes short explanations. Every AI answer is checked and thrown away if it fails.
- **Template mode only**: nothing extra. All recommendations work fully without AI.

- **Use Ollama Cloud with an API key**: nothing is downloaded. Paste your key from
  [ollama.com/settings/keys](https://ollama.com/settings/keys) when asked (the input is hidden). The key is stored
  only on your computer in `userdata/ollama_api_key.txt` and is never shown again. In this mode the sentences and the
  rule texts are sent to ollama.com; reviewer comments and your other answers never leave the computer. Your Ollama
  account needs usage credits or a plan ([ollama.com/plans](https://ollama.com/plans)); without them the app says so
  and continues in template mode.

You can switch between the three later in **Settings > AI** (local model, cloud model, save or remove the key).
For a copy with the cloud option preselected, build `dist/ClaimComposer-cloud.zip` with
`uv run python scripts/build_release.py --cloud` (it contains no key).

Then the app opens in its own window. **Keep the black launcher window open while you work; closing it stops the app.**
If setup is interrupted, double-click again and it continues where it stopped. If something fails, the window says what
to do next, and the details are in `logs/setup.log`.

## Install it permanently (optional)

| Your computer | Double-click | Installs to |
|---|---|---|
| Windows | `INSTALL_ClaimComposer.bat` | `%LOCALAPPDATA%\Programs\ClaimComposer`, desktop shortcut and Start menu entry |
| Mac | `INSTALL_ClaimComposer.command` | `~/Applications/ClaimComposer` and an app in *Applications* |
| Linux | `install_claimcomposer.sh` | `~/.local/share/claimcomposer`, menu entry and desktop shortcut |

To remove it, use `UNINSTALL_ClaimComposer.bat`, `UNINSTALL_ClaimComposer.command` or `uninstall_claimcomposer.sh`.
They ask separately whether to remove the AI model too.

## Using it

1. **Job ticket (left).** Answer one question at a time: product, audience, channel, what you want to say, what it
   covers, your evidence, comparison, timing, and language and tone. Use the arrow keys and Enter, or click. Backspace
   goes back. Each answer is stamped on the ticket; click a stamp to change it.
2. **Type case (top).** While you answer, the rules being selected appear as small type slugs.
3. **Proofs (right).** After the last answer the sentences are set as proof slips:
   - the sentence, with **placeholder chips** such as `[X]` that you can fill in; the sentence is checked again at once;
   - **Regulations** in the margin with article, legal status and a quoted passage;
   - **Why it fits** and **Facts to verify before use**;
   - **Copy**, **EN/DE**, **Tone** and **Show sources**.
4. **Don't say.** Phrases to avoid for this product, audience and channel, struck through, with the reason.
5. **Margin notes: the future.** Possible future requirements. These are not law.

If you have no evidence yet, the app shows **what to obtain first** instead of a sentence with figures.

**Job log** keeps every ticket on this computer and exports it as JSON, CSV or Markdown.
**Settings** switches the AI, the model, *Review mode* (rate each proof) and *Usability mode* (timings and the SUS
questionnaire), and can clear all local data.

## For developers

```bash
uv sync
```

```bash
uv run python -m app.main --open
```

```bash
uv run python scripts/build_library.py
```

```bash
uv run pytest
```

- `knowledge/` is the read-only knowledge base (see `docs/DATA_CONTRACT.md`).
- `library/` holds the questionnaire, templates, "Don't say" list and coverage report (see `docs/LIBRARY.md`).
- `app/engine/` routes answers to rules, selects and fills templates, validates them in code and adds the optional AI step.
- `scripts/build_release.py` writes `dist/ClaimComposer-portable.zip`.
- `scripts/visual_check.js` takes the screenshots used for the visual check (needs Node and Playwright).
- Model choice: `docs/MODEL_CHOICE.md`.
