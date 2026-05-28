# Reply to u/ISamohvalov on r/USCIS

**Thread:** https://www.reddit.com/r/USCIS/comments/1togz6h/built_a_model_that_predicts_the_next_visa/
**Comment:** https://www.reddit.com/r/USCIS/comments/1togz6h/comment/oo1cwvr/
**Their comment:** "Any predictions make no sense given the fact that the government can only predict by one month ahead with all available data they have"
**Profile context:** EB-2 PERM, ROW (Slavic name; previously hosed by the 7% cap reallocation that pulled visas from EB-2 into EB-1)

---

## Draft v3 (post-vintage-mismatch fix)

Fair — and your category specifically (EB-2 ROW, if I read your profile right) is one where you'd be justified clicking the archive and finding it looks bad.

The archive for ROW categories is contaminated with old experimental model outputs (`vqs_ensemble`, `oppenheim_pace`, `gbm_gated`) that the current code wouldn't pick. Current dispatch for EB-2 ROW at 1 month is just `regime_switched`, which on stalled-or-Current series collapses to the no-change line — i.e. the model agrees with you that it has nothing to add at 1m. The bad-looking historical rows are vintage cruft, not what current code would output.

I'm re-publishing the past months' archive with current dispatch so it actually reflects the model that exists today. And the accuracy numbers on the methodology page only cover the 6 oversubscribed series (India + China EB-1/2/3) — I'll note that explicitly; for ROW the published value is essentially "no change unless DOS moves it."

On the policy-shock argument: agreed, no statistical model handles a per-country cap reallocation. The forecast only claims value in the steady-policy regime between shocks, which is most months but not all.

---

## Draft v2 (shorter, less confrontational) — superseded

Yeah, that's true at 1 month — at 1m my model is about as good as just guessing "no change" (~41 days off on average), and I say so on the page.

Where I think it earns its keep is at longer horizons on the stalled series — 6-month MAE on China EB-3 / EB-2 and India EB-2 is in the 160–200 day range, vs ~228 for "assume no change." Not amazing, but useful if you're trying to plan a year out.

The December version really was just naive extrapolation, which is why I rebuilt it. Happy to be wrong on specific categories if you've seen one that looks off.

---

## Draft v1 (original) — superseded

Fair point, and partly true — Charlie Oppenheim has said the same thing publicly. The government has signals I'll never see (per-consulate processing capacity, internal demand letters from DOS).

But two things:

1. **People in the December thread were explicitly asking for predictions beyond what Charlie publishes.** The whole reason I rebuilt was that "wait and see one month at a time" wasn't a useful answer for someone deciding whether to switch employers, file an I-485 supplement, or accept a job offer. Even an imperfect forecast with honest uncertainty beats nothing.

2. **It's measurably better than the naive alternatives, which is what I can defend.** Current backtest numbers (every prediction vs the real DOS cutoff, public archive):
   - **1-month MAE:** ~41 days. Same as "assume no movement" (persistence). So at 1m I openly tell you the model adds ~zero value — most pages just show the flat-line baseline with a note.
   - **6-month MAE on the series people actually care about:** China EB-3 159d, China EB-2 176d, India EB-2 204d, India EB-3 261d. Persistence at 6m is ~228d average — the model beats it on 4/6 series, by ~15-30%.
   - **vs the old linear extrapolation in my December post:** 1m 41d vs 77d, ~half the error.

So: the absolute numbers are not small (a 6-month India EB-2 prediction can be ±7 months off), and I say so on every prediction page. But "useless" overstates it — there's a measurable gap vs both persistence and linear, and the long-horizon stalled-series predictions are the ones users said they actually wanted.

If you've got a specific category where you think the archive looks wrong, I'd want to see it.

---

## Notes for sender

- v3 concedes his point lands (the archive *did* look bad for his category) AND announces the fix in the same breath. Lower-confrontation, more credible.
- Don't post v3 until the re-publish has actually run on prod (otherwise the claim "I'm fixing it" rings hollow when he clicks the archive 30 min later).
- u/ISamohvalov has 1 karma on this comment — low engagement; reply is mostly for other readers.
- Tone match: same energy as the prior "Fair — one of the categories the model is most volatile on" reply.
