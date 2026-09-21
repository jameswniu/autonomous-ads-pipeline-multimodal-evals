> Read-only review by a second vendor's model of the working directory that preceded this repo. Filenames it cites (`data.json`, `points.jsonl`, `brief.md`) are that directory's. `judge_scores.jsonl` here is its `points.jsonl`; the clip-to-vote join it criticises in finding 2 is corrected in `eval/run.py`. Kept verbatim. See `PROVENANCE.md`.

I couldn’t write `astra-findings.md` because this session prohibits filesystem writes. The report follows.

1. **The reported rule is a post-generation selector, not a pre-generation router.**

   Its inputs include eight frames from every candidate clip. Those inputs require paying to generate the candidates first. The product question requires choosing an engine from information available before generation. No aggregation change resolves that mismatch. (`brief.md:9`, `brief.md:17`.)

   The supplied data can evaluate selection among rendered clips. They do not establish a deployable mapping from a new brief to an engine. The files contain clip scores and brief identifiers, but no supplied representation of the briefs’ contents. (`data.json:34–66`.)

2. **The clip-to-human-label join mixes shoots. This materially changes the result.**

   `data.json` selects one clip per brief–engine, sometimes from August 26, while its human rates pool votes for that engine across both shoots. For example, slowroad’s selected seedance2 clip is August 26; its direct comparison against wan3 uses August 24. (`data.json:59–63`; `pairs.json:380–389`, `pairs.json:432–441`.)

   Computed from the raw votes:

   - August 24 slowroad seedance2: **26 wins / 37 decisive votes = 70.27%**.
   - August 26 slowroad seedance2: **2 / 8 = 25.00%**, against omni only.
   - Pooling them: **28 / 45 = 62.22%**, reproducing `data.json:30`.

   Yet the corresponding Claude sums are **17.55** for August 24 seedance2 and **13.25** for August 26 seedance2. Wan3 scores **17.00**. Thus, against the seedance2 clip actually shown in the wan3 comparison, Claude’s mean score favors seedance2. (`data.json:113–124`, `data.json:146–148`; vote aggregation from `votes.csv:2–451`, joined through `pairs.json`.)

   This does not prove that pooling shoots is always invalid: it could target average engine performance across renders. But pairing that pooled outcome with the score of one selected render needs an explicit justification. These data do not supply one.

   A defensible diagnostic is to use the **August 24 cohort**, because it contains all six engine comparisons for every brief. Matching its scores to its votes gives these fixed-sum routes:

   | Harbor | Lantern | Orchard | Quiet | Slowroad | Human rate |
   |---|---|---|---|---|---:|
   | seedance2 | wan3 | wan3 | wan3 | omni | **47.37%** |

   Its corresponding empirical uniform baseline is **49.80%** and oracle **67.60%**, using the original decisive-vote, pooled-opponent metric. These are computed from August 24 records in `pairs.json:2–391`, `votes.csv:2–451`, and Claude means in `data.json:68–127`. This is a sensitivity analysis with correctly matched clips, not a new estimate of future engine performance.

3. **The metric needs an explicit opponent distribution and tie policy.**

   I reproduce **49.722% uniform, 59.379% selected, and 65.990% oracle** from raw votes by dropping ties and pooling each engine’s decisive votes across its observed opponents and shoots. There are **60 ties among 450 votes**. (`votes.csv:2–451`; rounded rates in `data.json:2–32`.)

   Consequently, the stated metric is conditional on a decisive response. Unequal comparison counts also give different engines different opponent mixtures. That is why “uniform” is not exactly 50%.

   For a complete four-engine cohort, define an engine’s value as its average preference probability against the other three engines, with ties worth one-half. Uniform then equals **50% algebraically**. On the August 24 cohort, that definition gives:

   - Fixed-sum selector: **47.87%**.
   - Empirical oracle: **66.01%**.

   These computed alternatives use the same records as finding 2. Neither definition should be selected because it produces the desired lift. Freeze the target before comparing methods.

4. **Quiet and slowroad do not share a supported score-level failure mechanism.**

   Under the supplied mixed-shoot mapping, the Claude axis means are:

   | Brief | Engine | Craft | Message | Warmth | Sum |
   |---|---|---:|---:|---:|---:|
   | quiet | seedance2 | 5.90 | 5.85 | 4.20 | 15.95 |
   | quiet | wan3 | 5.40 | 6.00 | 4.65 | 16.05 |
   | slowroad | seedance2 | 5.00 | 4.95 | 3.30 | 13.25 |
   | slowroad | wan3 | 6.00 | 6.00 | 5.00 | 17.00 |

   Sources: `data.json:104–106`, `data.json:119–124`, `data.json:146–148`.

   **Quiet is unresolved judge noise plus an axis tradeoff.** Its 0.10-point difference has an estimated independent-call standard error of **0.251**. Across all 400 cross-comparisons of the two clips’ 20 total scores, wan3 wins **153**, ties **122**, and loses **125**. These comparisons summarize the distributions; they are not 400 independent observations. Computed from quiet records in `points.jsonl:13–606`.

   **Mapped slowroad is different.** Wan3 scores 17 in all 20 calls; mapped seedance2 scores 12 once, 13 thirteen times, and 14 six times. Wan3 wins all **400/400** cross-comparisons and dominates every axis mean. Any positively weighted sum of those means must prefer wan3. Computed from `points.jsonl:19–615`.

   Nor does a small-margin rule uniquely identify the misses. The winner–runner-up mean gaps are **0.35, 0.00, 0.20, 0.10, 0.60** for harbor through slowroad. Lantern and orchard are correct despite smaller gaps than slowroad. (`data.json:68–151`, mapped by `data.json:34–64`.)

   The supported distinction is therefore: quiet is fragile; slowroad’s apparent contradiction is strongly affected by clip identity. There is no demonstrated common signature identifying both mistakes.

5. **Variants offer some support for reconsidering quiet, but not a general correction rule.**

   Summing each variant’s own axes gives these seedance2/wan3 comparisons:

   | Variant | Quiet: seedance2 / wan3 | Mapped slowroad: seedance2 / wan3 |
   |---|---:|---:|
   | V0 baseline | 16 / 15 | 13 / 17 |
   | V1 new axes | 23 / 21 | 17 / 22 |
   | V2 anchored | 24 / 20 | 18 / 22 |
   | V3 per-call | 15 / 14 | 17 / 24 |
   | V4 few-shot | 22 / 19 | 18 / 24 |
   | V5 justification | 22 / 23 | 19 / 24 |
   | V6 fine scale | 157 / 153 | 146 / 179 |

   Sources: `points-variants.jsonl:13–23`, `:42–54`, `:70–82`, `:98–111`, `:127–138`, `:154–166`, `:181–195`. Totals are compared within variants, not across their different scales.

   Quiet’s seedance2 beats wan3 in **6/7** variants, including the separate baseline call. Slowroad’s mapped seedance2 loses in **7/7**. However, beating wan3 does not always mean winning the four-engine selection: V3 selects omni for quiet; V6 selects heygen alphabetically from a three-way tie.

   Variant disagreement also occurs among the supposedly correct calls. Harbor’s V3 and V4 winners are wan3; lantern’s V2 and V6 winners are wan3. (`points-variants.jsonl:141–168`, `:85–112`, `:57–84`, `:169–196`.) Disagreement is not a specific error detector.

   **LOBO design:** for a fixed, equally weighted variant-rank ensemble, hold out every label for one brief, compute that brief’s ranks using frozen variants, and select nothing on the other four. If choosing variants or weights, perform that selection entirely inside the four-brief training fold. Choosing the ensemble after observing its full-data improvement remains exploratory.

6. **Aggregation alternatives mostly preserve the ordering; the apparent Borda repair is fragile.**

   The table uses the supplied mapping, alphabetical final ties, and rounded human rates from `data.json:2–32`. Route order is harbor, lantern, orchard, quiet, slowroad. O = omni, S = seedance2, W = wan3, H = heygen.

   | Aggregation | Routes | Human rate |
   |---|---|---:|
   | Mean of total scores | O, S, W, W, W | 59.36% |
   | Median of total scores | O, S, O, O, W | 58.26% |
   | Sum of three axis medians | H, S, O, O, W | 55.84% |
   | Borda of total scores within matched rep numbers | O, S, W, S, W | **64.44%** |
   | Borda across the three axis means | S, S, W, W, W | 54.64% |
   | Average Borda over individual axes and matched reps | O, S, W, W, W | 59.36% |
   | Plurality across reps, splitting tied first places | O, S, W, W, W | 59.36% |
   | Borda using all cross-rep comparisons | O, S, W, W, W | 59.36% |
   | Bradley–Terry on cross-rep implied preferences | O, S, W, W, W | 59.36% |

   Computed from Claude records in `points.jsonl:1–616`, using `data.json:34–64`. Borda awards one point per opponent beaten and half per tie.

   These are all **pre-specifiable algorithms**, but none becomes historically pre-specified because it is conventional. Medians assume robustness to exceptional scores matters; ranks discard score distances; neither is automatically better for human preference.

   The matched-rep Borda result deserves particular skepticism. Quiet gives seedance2 and wan3 exactly **2.10 Borda points each**; alphabetical order supplies the “improvement.” Independent pointwise calls have no established cross-clip pairing merely because both are numbered rep 7. Independently permuting rep order within each quiet clip 10,000 times selected wan3 **75.44%** and seedance2 **24.56%** of the time; the clip score distributions never changed. This computation used seed 44.

   The permutation-invariant cross-rep Borda scores instead favor wan3 **2.065 versus 1.990**. Bradley–Terry preserves that choice. For the latter, I used cross-rep preference probabilities scaled to 20 effective comparisons per engine pair, plus half a pseudo-win each way to avoid infinite estimates under complete separation. Lantern’s identical score distributions remain an exact tie.

   **LOBO design:** evaluate each frozen aggregator independently, holding out all human labels for one brief and selecting nothing. If selecting among the table’s methods, maximize training-fold routing value on the other four and predeclare mean aggregation as the first tie-break. That selection procedure produces the original five routes, **59.36%**: when quiet is held out, its apparent Borda advantage is absent from training. Selecting Borda from its full-data 64.44% would fit the answer.

7. **Margins can train a model legitimately, but only across held-out briefs and correctly matched clips. I tested one such design.**

   A pair’s empirical preference probability is a useful soft target. For decisive counts \(w\) wins and \(n-w\) losses, let \(q=w/n\). Fit

   \[
   P(A\succ B)=\sigma\!\left(\beta^\top(s_A-s_B)\right)
   \]

   with the actual clips’ three mean scores. Weight cross-entropy by \(n\); this retains the distinction between 6–4 and 60–40. Normalize within brief so each training brief has equal total weight. Do not additionally weight by observed absolute margin without a separate justification: that changes the objective toward apparently easy pairs.

   I executed this exploratory nested LOBO design:

   - Outer fold: hold out **all votes from both shoots of one brief**.
   - Train on correctly joined pairs from the other four briefs.
   - Constrain the three axis coefficients to be nonnegative.
   - Use ridge penalty \(\lambda\|\beta\|^2/2\).
   - Select \(\lambda\in\{0.01,0.1,1,10\}\) by inner LOBO on the four training briefs, minimizing held-out soft-label cross-entropy.
   - Refit on all four; select among the held-out brief’s August 24 clips.
   - Evaluate against that brief’s August 24 human outcomes.

   The selected penalties were **1, 0.1, 10, 10, 10**. Routes were **seedance2, wan3, wan3, seedance2, omni**, scoring **52.44%**, versus **47.37%** for the matched fixed sum. Inputs: `pairs.json:2–443`, `votes.csv:2–451`, `data.json:68–151`.

   This is evidence that margin fitting is executable without direct fold leakage, not evidence of a confirmed improvement. The model family was formulated after examining these data, and it remains post-generation. Importantly, it does not support the original 59.4%-to-66.0% story.

8. **The brief-bootstrap significance claim does not reproduce; the rater-bootstrap claim approximately does. Neither corrects model selection.**

   Using exact vote-derived rates, the fixed mapped router’s per-brief lifts are:

   **+14.483, +17.070, +20.543, −9.455, +5.641 percentage points.**

   Enumerating all **\(5^5=3,125\)** ordinary bootstrap samples of those five briefs gives:

   - Mean lift: **+9.656 points**.
   - Percentile 95% interval: **[−0.436, +17.942] points**.
   - Bootstrap fraction at or below zero: **0.03232**.

   That differs materially from **[+3.6, +17.4], 0.010** in `brief.md:17`. Rounded `data.json` rates produce essentially the same contradiction. Unless a different bootstrap definition was used, the reported brief interval is wrong.

   Resampling the **90 participants**, preserving each participant’s vote bundle, does reproduce the other result: 100,000 resamples gave **[+2.84, +16.22] points**, with nonpositive fraction **0.00288**. Computed from `votes.csv:2–451`, seed 270921. This conditions on the observed briefs, clips, mapping, and selected rule; it does not establish generalization to new briefs. A bootstrap tail fraction is also not automatically a calibrated hypothesis-test p-value.

   “Within-pair permutation” is insufficiently specified to reproduce **p=0.0045**. Permuting existing winner labels among raters within a pair preserves its margin and cannot change this aggregate routing statistic. Independently swapping engine outcomes defines a different null and requires attention to repeated participants.

   Finally, if Claude was selected using these same votes, the configuration is **not prospectively fixed**, even if the selection criterion was per-pair prediction rather than routing. Both criteria depend on the same preference outcomes. Every label-informed choice must be repeated inside each outer training fold—or inside each permutation if testing the entire selection procedure. The available files do not document the complete historical search, so a selection-adjusted p-value cannot be reconstructed. This is the standard selection-bias problem described by [Cawley and Talbot](https://www.jmlr.org/beta/papers/v11/cawley10a.html). (`brief.md:22`, `brief.md:47`.)

9. **Two additional claims need correction.**

   **More reps did change routing.** With the supplied mapping, rep 1 and alphabetical ties select **O, O, W, S, W**; 20-rep means select **O, S, W, W, W**. Lantern improves, but quiet deteriorates. With uniformly random selection among exact top ties, the expected human rate changes from **59.107% to 56.335%**, a **−2.772-point** difference—not zero. Sources: first-call records `points.jsonl:1–28`; full means `data.json:68–151`; claim `brief.md:27`.

   **Inter-rater agreement is not a prediction ceiling.** Even if the stated agreement is 53%, that does not cap prediction accuracy at 53%. For a simple pair with independent votes and preference probability \(p\), agreement is \(p^2+(1-p)^2\), while the optimal constant prediction achieves \(\max(p,1-p)\). Agreement of 53% is compatible with **62.25%** optimal accuracy. This is an algebraic counterexample to the ceiling claim, not a re-estimation of the dataset’s ceiling. (`brief.md:23`.)

10. **The contextual-bandit framing cannot establish that 41% of the gap is irreducible.**

    A pre-generation policy could be formulated as a four-arm contextual bandit if it receives brief features before acting and has a defined reward. That is the usual sequence: observe context, choose action, observe reward. ([Agarwal et al.](https://proceedings.mlr.press/v22/agarwal12.html).)

    Here, the observations are repeated human comparisons among already generated clips. The **450 votes** help estimate preferences for those clips; they do not create 450 independent brief contexts or repeated generation outcomes. The **five contexts** and mixed-shoot structure remain. (`brief.md:7`; `pairs.json:2–443`.)

    A numerical illustration shows why generic bounds offer little: even assuming five independent contexts and perfectly observed bounded rewards, the usual Hoeffding union bound for just **four fixed policies** has 95% error radius

    \[
    \sqrt{\frac{\log(2\cdot4/0.05)}{2\cdot5}}=0.712.
    \]

    That is **71.2 percentage points**, already vacuous for this decision. Realistic label and render uncertainty do not improve it.

    A vacuous upper bound is not a lower bound on achievable performance. These data cannot distinguish an easy world with a learnable brief–engine relationship from one with unpredictable render variation. Also, **66.0% is a maximum of noisy empirical estimates**, so it is an optimistic benchmark for the population oracle. The residual gap is neither a proven noise floor nor a measured irreducible regret.

11. **The principled next step is to repair the evaluation and establish a genuinely pre-generation baseline.**

    Freeze clip identity, opponent weighting, and tie handling. Treat the complete August 24 cohort as the primary matched comparison, with the four August 26 pairs as a separately reported sensitivity analysis. In every outer fold, hold out both shoots of the entire brief.

    Then include the simplest deployable rule: **choose the engine with the highest mean human value on the other four briefs**, treating all engines symmetrically and using alphabetical ties. This is a pre-specifiable learning procedure, not a hard-coded preference for seedance2.

    I computed that LOBO baseline:

    | Evaluation definition | Held-out routes | Human rate |
    |---|---|---:|
    | Supplied pooled-shoot metric | S, O, S, S, S | **54.49%** |
    | August 24, original decisive-vote metric | S, S, S, S, S | **59.57%** |
    | August 24, equal opponents and half-credit ties | S, S, S, S, S | **58.64%** |

    Computed from `pairs.json:2–443` and `votes.csv:2–451`. Each engine is selected using only the other four briefs’ labels. The resulting seedance2 preference is learned inside folds; it is not specified from the two misses.

    This remains exploratory evidence from five briefs, but it is executable before generating the next clip. On the matched cohort it also outperforms both the fixed sum and the tested margin model. Any proposed contextual router should first beat this baseline using only inputs available before rendering.

## VERDICT

The main gap is in the experiment’s interpretation: a post-generation selector is being presented as a pre-generation router, scores and human outcomes refer to different mixtures of clips, and the brief-bootstrap significance claim does not reproduce. Quiet is a plausible aggregation-sensitive mistake; slowroad is substantially a clip-identity problem. No tested aggregation provides a defensible general repair. Repair the joins and metric, evaluate complete learning procedures with whole-brief holdouts, and benchmark against the training-fold best constant engine. The current evidence supports neither a validated 59.4% pre-generation router nor a claim that the remaining 41% of empirical headroom is irreducible.