# Letter Explainer: Notes

> DRAFT. Replace every **[FILL IN]** with what actually happened when you ran it. Keep only what's true.

**Intended user:** Someone who gets a confusing government letter (DMV, FTB/IRS, county tax) and isn't sure what it means, what they owe, or what the real deadline is. For example, my family, or me. **[FILL IN: one sentence on your personal connection]**

**Problem / current workaround:** People reread the letter, Google phrases, call the agency and wait on hold, or set it aside and miss a deadline. A better outcome: in under a minute, know what it is, what you owe, every deadline, and what to do next, with confidence the numbers are right.

**First approach:** Paste letter text → Claude returns structured JSON → show it on a simple page.

**Assumption to test:** That the AI's dates and amounts can be trusted. In a tax or DMV letter, a wrong number is worse than no answer.

**Alternative considered:** Pure rule-based extraction (regex for dates and amounts). It's reliable for numbers but can't explain *why* you got the letter or what to do. I kept it as an offline fallback and, more importantly, as the **checker** for the AI's output: every date and amount the AI reports must appear in the original letter, and the prompt tells the AI never to calculate new numbers. The FTB sample includes an optional $34 installment fee; adding it to $793.91 gives a plausible but wrong $827.91, which is exactly what the checker flags.

**Decision changed after trying it:** Deadline detection first read the letter one line at a time. Testing the FTB notice showed it missed the protest deadline, because the letter splits "postmarked no later than" and "November 21, 2026" across two lines. I changed it to look at the text just before each date, with line breaks removed. A second fix from the same letter: amounts printed with padding ("$   793.91") weren't recognized until I allowed spaces after the dollar sign.

## Test results

| Input | Expected | What happened | How I checked |
|---|---|---|---|
| Normal: DMV renewal | Due $296.00, deadline Nov 15, 2026, smog check step | Offline: correct, all verified. AI: **[FILL IN]** | Compared against the letter by hand; all ✓ badges |
| Difficult: FTB notice | Two deadlines (pay by Oct 22, protest by Nov 21), $793.91, $34 fee not added | **Bug found:** the protest date was missed because the letter wraps "no later than / November 21" across two lines. Fixed by checking the text before each date instead of splitting by line. AI: **[FILL IN]** | Unit test `test_missed_deadline_is_flagged` |
| Invalid: grocery receipt / too-short text | Say it isn't a letter; reject short input before the AI call | Receipt marked "not an official letter"; short input rejected with a clear message | Unit tests |
| Unusual: Spanish property tax bill | AI explains in English; dates are hard to verify | AI: **[FILL IN]**. Spanish dates can't be verified, so they're flagged (known limitation) | Visual check |

**Catching plausible-but-wrong answers:** (1) value-level matching of every date and amount against the source letter, (2) flagging deadline-like dates the AI didn't list, (3) a prompt rule against calculating numbers, (4) a red "double-check" banner whenever anything fails. Unit tests simulate an invented total, a miscalculated deadline, and a missed deadline.

**Tools used:** Python standard library; Claude API (AI mode); Render (free hosting); Claude as an AI coding assistant, which generated the initial code, sample letters and tests. I reviewed, ran and tested them. **[FILL IN: what you changed yourself]**

**Reused work/templates:** None. All sample letters are fictional.

**Time spent:** **[FILL IN, ≤ 4 hours]**

**Known limitations / unfinished:** English-only date verification; verifies a number *exists* but not that it's labeled correctly; text paste only (no PDF/photo OCR); not legal or tax advice.

**Next:** Most important open assumption: do users trust the ✓/⚠ badges, or do they still call the agency? I'd ask a user: "After reading this, would you still call? Why?" Success measures: time to understand a letter, deadlines missed, and how often the summary matches what the agency says.
