# Letter Explainer

**Live demo:** _add your Render URL here_ · **Walkthrough video:** _add your video link here_

Paste a confusing official letter (DMV, FTB/IRS, county tax bill) and get:

- a plain-English summary of what it is and why you got it
- every deadline, and what has to happen by each one
- the amount you owe, plus every other amount mentioned
- a checklist of what to do next
- **a verification check**: every date and dollar amount in the explanation is matched against the original letter, and anything that can't be found is flagged in red

> The live demo runs on a free hosting tier that sleeps when idle, so the first load can take up to a minute.

## Run it locally (no installs needed)

Requires Python 3.9+. Uses only the standard library.

```bash
# Optional: enable AI mode (Claude). Without a key the app runs in offline demo mode.
export ANTHROPIC_API_KEY=sk-ant-...          # Windows PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."

python app.py
```

Then open http://localhost:8000. Click a sample under the text box, or paste your own letter, and press **Explain this letter**.

## Two modes (clearly labeled in the app)

| Mode | When | What happens |
|---|---|---|
| **AI mode** | `ANTHROPIC_API_KEY` is set | Claude reads the letter and returns structured JSON (summary, deadlines, amounts, steps, warnings). The verifier then checks every number. |
| **Offline demo mode** | No key, or the daily AI limit is reached | **Rule-based, no AI.** Finds dates near deadline words and dollar amounts, and quotes the surrounding text. |

The model defaults to `claude-sonnet-5-5`; override it with `LETTER_MODEL`.

## Sample inputs (all fictional)

| File | Test type |
|---|---|
| `samples/1_normal_dmv_renewal.txt` | Normal: one deadline, one total |
| `samples/2_difficult_ftb_notice.txt` | Difficult: two deadlines with different consequences, penalty + interest, an optional fee that should **not** be added to the total |
| `samples/4_unusual_spanish_property_tax.txt` | Unusual: official letter in Spanish, two installments |
| `samples/3_invalid_grocery_receipt.txt` | Invalid: not an official letter |
| `samples/5_invalid_too_short.txt` | Invalid: incomplete input |

## Tests

```bash
python -m unittest discover tests -v
```

The verifier tests simulate plausible-but-wrong AI answers (an invented total, a miscalculated deadline, a missed deadline) and confirm each one is flagged.

## How it works

```
letter text ──► check_input()   reject empty, too-short or too-long input before any AI call
            ──► explain()       Claude → JSON   (or rule-based in offline mode)
            ──► verify()        every date/amount must exist in the letter;
                                also flags deadline-looking dates the AI didn't list
            ──► web page        summary, amount due, deadlines, checklist, ✓ / ⚠ badges
```

| File | Purpose |
|---|---|
| `explainer.py` | Input checks, the Claude prompt, offline rules, and the verifier |
| `app.py` | Small web server (standard library), daily AI limit, request size limit |
| `index.html` | The page |
| `tests/` | Unit tests |
| `samples/` | Fictional test letters |
| `render.yaml` | Hosting config for Render |
| `NOTES.md` | One-page notes: approach, decisions, test results, limitations |

## Deploy (Render, free tier)

1. In Render, choose **New > Blueprint** and select this repository. Render reads `render.yaml`.
2. Paste your `ANTHROPIC_API_KEY` when asked.
3. Deploy. Render gives you a public URL.

`DAILY_AI_LIMIT` (default 200) caps Claude calls per day so a public link can't run up the bill. After the cap, the app falls back to offline mode and says so. Also set a monthly spend limit in the Anthropic Console.

## Built with AI assistance

I used Claude as a coding assistant to generate the first version of the code, the sample letters and the tests. I chose the problem and the design, reviewed and ran the code, tested it, and made the changes described in `NOTES.md`.

## Known limitations

- Verification only understands English date formats. Spanish dates ("10 de diciembre de 2026") can't be checked, so they're flagged as unverified.
- Verification proves a number **appears** in the letter, not that it's attached to the right meaning (e.g., the AI could swap two real dates), or that the letter's own math adds up.
- Text input only. No PDF or photo upload (OCR) yet.
- Not legal or tax advice.
