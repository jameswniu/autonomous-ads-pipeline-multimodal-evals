# The shoot, tier by tier

The README states the argument. This is the record behind it: one autonomous ad
production, twenty-eight versions across five invented brands and ten spec ads for
real products, with every render gated before a dollar moved. Each tier below is
the section that used to sit on the front page, verbatim, with the ledgers each
number comes from. Three tests read these tables and fail if a number here stops
matching the ledger it cites.

## 1. Process evals

Process evals check how the work got made, before anyone looks at the result. The industry name is process supervision.

- Every step has a contract, the contract is checked the moment the step runs, and a failed check stops the job before the next dollar is spent.
- The source of truth is the pipeline graph, an orchestration framework such as LangGraph in most stacks and plain scripts here. This tier moves only when the scripts move.
- The exact scripts that ran are in this repository. Boards, batch drivers and ledgers in [`shoots/`](shoots/), the board probe, caption gate and closer checks in [`gates/`](gates/), the pixel probes in [`probes/`](probes/), the pre-spend guards in [`guards/`](guards/). The code map near the end says what each file is. Look generation stays out: it ran against the avatar vendor's account, with its own framing checks on the still, head and body inside the crop and shot size, and the closer path here starts from its output.

| Step | What it has to prove before the next step may start | How it fails |
|:---|:---|:---|
| Board | Five mechanical checks, free, before a cent is spent (the product absent before the payoff, the escalation declared, the quirk never spoken by the narration, mouths closed under narration, the centre-crop clause present), then four judgment rows I score 0 to 3 by eye | The board goes back |
| Render | Every request and every landing appended to the ledger, the vendor's own rejection text included | Recorded, re-rolled once with one variable moved |
| Closer | Identity pin on the voice and avatar ids, prop gate on the look, jaw measured on the raw render and refused over the band | Pre-spend |
| Build | The closer's video starts within 40 ms of where its audio was placed | Frame-exact, on the master |
| Ad gates | Every burned cue says what is spoken, within 0.5 s before or 0.3 s after its first word. The closer's mouth is not late | Blocks delivery |
| Ship gate | Loudness, true peak, silence tail, the standing disclosures. Exit 64 on unreadable input | Fails closed |
| Deliver | A defective delivered cut is withdrawn, replaced, and the withdrawal ledgered with its reason | On the record |

### The redo, as a ledger reads it

Four invented-brand spots were shot again after I kept rejecting boards. I review every cut by eye, and I am the only human in the loop.

- The grammar that survived is the one I named. Open absurd at three or four times the volume, hand over the coherent model by the second line, and keep every quirk visual with nobody narrating it.
- Each spot shipped two ways. One leg ran on the engine that won its panel in the four-engine race in section 3, the other on Omni Flash, from the same boards, narrations, closers, beds and captions. The only variable between the columns is the engine.
- The [ledgers](shoots/) hold four rounds behind them, 16, 16, 12 and 15 engine requests, 59 in all, two of them music beds, for eight shipped versions.
- Two of those rounds built four masters each and neither shipped.

<table>
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260826-cell-seedance2-orchard.gif" alt="Orchard Hill Coffee redone, Seedance 2.0" width="100%"><br><b>Orchard Hill Coffee, Seedance 2.0, the WINNER.</b> <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260826-seedance2-orchard.mp4">&#9654; with sound</a></td>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260826-cell-omni-orchard.gif" alt="Orchard Hill Coffee redone, Omni Flash" width="100%"><br><b>Orchard Hill Coffee, Omni Flash.</b> <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260826-omni-orchard.mp4">&#9654; with sound</a></td>
  </tr>
</table>

| Process record, Orchard Hill Coffee | Seedance 2.0 | Omni Flash |
|:---|:---|:---|
| Scene renders in the ledger across the rounds, re-rolls included | 11 | 3 |
| Caption gate on the shipped master | PASS, 5 cues | PASS, 5 cues |
| Closer video against its audio placement | 0 ms | 0 ms |
| Mouth sync on the shared closer | PASS, +0.08 s | PASS, +0.08 s |
| Master that shipped | v3 | v1 |

The three redo winners' clips sit on the front page under the race, where the race ledger pins them.

| The other three spots | Renders in the ledger, winner's engine and Omni | Mouth sync on the shared closer | Masters that shipped |
|:---|:---|:---|:---|
| Lantern Street, Wan 3.0 | 8 and 3 | REVIEW, 0.00 s, eye approved | v7 and v1 |
| Harbor Lane Realty, Wan 3.0 | 12 and 5, the sign scene re-rolled for an invented phone number | PASS, 0.00 s | v5 and v2 |
| Slow Road Travel, Seedance 2.0 | 11 and 4 | REVIEW, +0.04 s, eye approved | v4 and v1 |

Every one of the eight masters passed the caption gate at five cues and held its closer at 0 ms drift. REVIEW means the mouth probe could not read the closer well enough to rule and handed the call to me, and the ledger says so. All eight cuts are in the [media release](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/tag/media-2026-08), with sound.

- Prompt-level constraints, written in the strongest form available, held on 6 of 15 attempts. A pre-call hook made the outcome right on 14 of 15, measured in [docs/ENFORCEMENT.md](docs/ENFORCEMENT.md). I now rank constraints by what happens when they are violated, and anything whose violation is silent gets a mechanism.
- The face-located mouth probe went in with its sign inverted and doubled the error it was built to remove. The gate caught it on the master. Three days later the same sign confusion came back in a different builder and reached the review thread, where a frame-by-frame audit found it rather than a probe. That auto-alignment is off now, and the check that replaced it is a frame ladder read by eye.
- Four guards protect the render path and three approve everything when a file they depend on goes missing. Two of the three do not know they are doing it, so a missing file looks exactly like a pass.

---

## 2. Outcome evals

Outcome evals check the artifact against the facts and do not care how it got made. The research literature calls this outcome supervision, and in retrieval terms it is a groundedness check.

- The claim on screen is compared with the source it was pulled from. How confident the model sounded does not count.
- In most stacks those facts arrive through retrieval, the RAG layer. Here they arrived through a pairwise research pass, one engine scanning the company's live pages and the other told to refute what it found.
- Either way the whole tier is re-derived when the brief changes.

For an ad, true means four things.

- The claim a spot closes on is the claim the company actually makes, in its own current words.
- The words on screen are the words being spoken, and the words being spoken are the script. The caption gate checks the first half. A transcription diffed against the script before any render is paid for checks the second.
- A prop that carries the story reads in the delivered crop.
- Hook rate, hold rate and view-through belong to the media buy, downstream of this pipeline. Everything measured on the creative before the buy is a proxy, and is labelled one.

### Ten real products, and nothing bends to the render

The invented brands were the easy case, because a story can bend to whatever the engine renders well. So the same loop ran against ten real, currently shipping AI products.

- All ten shot on Omni Flash at about sixty-three cents a scene, thirty scenes across two batches.
- Each master was gated on caption timing, closer alignment and lip sync before it was allowed out.
- These are spec ads. They are not affiliated with, endorsed by, or produced for Google, OpenAI, Perplexity, Meta, xAI, Z.ai, Moonshot AI or Anthropic. None of these companies has seen them, and every tagline is written here.

<table>
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-cell-claude.gif" alt="Claude spec ad" width="100%"><br><b>Claude.</b> Forty versions of you are arguing around the table and every one of them is sure. <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-claude.mp4">&#9654; with sound</a></td>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-cell-claudecode.gif" alt="Claude Code spec ad" width="100%"><br><b>Claude Code.</b> His code grew legs overnight and finishes the feature while he sips the coffee. <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-claudecode.mp4">&#9654; with sound</a></td>
  </tr>
</table>

<table>
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-cell-pics.gif" alt="Google Pics spec ad" width="100%"><br><b>Google Pics.</b> The photo is almost right, and almost is the thing that ruins it. <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-pics.mp4">&#9654; with sound</a></td>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-cell-gemini.gif" alt="Gemini spec ad" width="100%"><br><b>Gemini.</b> Your head has forty tabs open and not one of them is labelled. <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-gemini.mp4">&#9654; with sound</a></td>
  </tr>
</table>

<table>
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-cell-zai.gif" alt="Z.ai spec ad" width="100%"><br><b>Z.ai.</b> Her studio apartment is smaller than the problem she's solving. <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-zai.mp4">&#9654; with sound</a></td>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-cell-kimi.gif" alt="Kimi spec ad" width="100%"><br><b>Kimi.</b> She has one question and a library's worth of everything else. <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-kimi.mp4">&#9654; with sound</a></td>
  </tr>
</table>

<table>
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-cell-chatgpt.gif" alt="ChatGPT spec ad" width="100%"><br><b>ChatGPT.</b> It is never the big decisions that eat the evening. <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-chatgpt.mp4">&#9654; with sound</a></td>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-cell-perplexity.gif" alt="Perplexity spec ad" width="100%"><br><b>Perplexity.</b> Four hundred tabs, ten blue links, and still no answer. <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-perplexity.mp4">&#9654; with sound</a></td>
  </tr>
</table>

<table>
  <tr>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-cell-metaai.gif" alt="Meta AI spec ad" width="100%"><br><b>Meta AI.</b> Some days the list unrolls right out the front door. <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-metaai.mp4">&#9654; with sound</a></td>
    <td width="50%" align="center" valign="top"><img src="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-cell-grok.gif" alt="Grok spec ad" width="100%"><br><b>Grok.</b> The whole street changes its mind three times before your coffee cools. <a href="https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-grok.mp4">&#9654; with sound</a></td>
  </tr>
</table>

| Spot | The claim it closes on | Checked against | |
|:---|:---|:---|:---|
| Claude | A thoughtful collaborator for serious work, until the answer is one page | claude.com and anthropic.com | [&#9654;](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-claude.mp4) |
| Claude Code | The agent in your terminal that reads the codebase, fixes the bugs and ships the feature | The product page and its documentation | [&#9654;](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-claudecode.mp4) |
| Google Pics | Image creation and editing that brings your exact vision to life, down to a single object | Google's own I/O 2026 announcement | [&#9654;](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-pics.mp4) |
| Gemini | Google's personal assistant, hands free, across the apps you already use | gemini.google.com | [&#9654;](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-gemini.mp4) |
| Z.ai | Frontier open models, the same weights the big labs guard, priced for builders | z.ai and its developer documentation | [&#9654;](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-zai.mp4) |
| Kimi | A million pages read in a breath, answered with the one line that matters | moonshot.ai and kimi.com | [&#9654;](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-kimi.mp4) |
| ChatGPT | Help with everyday questions and ideas | OpenAI's ChatGPT overview page | [&#9654;](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-chatgpt.mp4) |
| Perplexity | An answer engine that hands back the answer with its sources attached | Perplexity's hub and help centre | [&#9654;](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-perplexity.mp4) |
| Meta AI | A personal agent that works on your behalf | Meta's own page on personal agents | [&#9654;](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260827-metaai.mp4) |
| Grok | Real-time answers with the sources still warm, from where news breaks first | x.ai and its developer documentation | [&#9654;](https://github.com/jameswniu/autonomous-ads-pipeline-multimodal-evals/releases/download/media-2026-08/shoot-20260830-grok.mp4) |

The first batch landed fifteen scenes on fifteen requests with zero content rejections. The second spent three re-rolls on art direction, none on defects.

- A For Sale sign that read perfectly in the raw 16:9 render shipped as OR SALE. The build cuts a centre square, and the engine had filled the width. Any scene whose beat is legible text is now composed small and dead centre, and checked in the square before the build. A probe flags a bright prop straddling a frame edge. It also fires on crowds and lamps, so it flags and I decide.
- A billboard of corrupted headline text was pulled for being illegible, replaced with clean colour fields, and then put back. The rule exists for fake logos and readable gibberish, and the glitch was the point. An outcome check has to know what the brief meant, and the rule alone cannot tell it.

---

## 3. Quality evals

Quality evals are the tier everyone argues about, so I made them the most mechanical of the three.

- A quality check, in practice, is a person watching a clip and saying good enough or not. I did that first, on the 78 labelled exemplars behind the thresholds and the 42 eye-labelled scenes behind the judge. Then the verdicts were compiled into numbers a scheduler can enforce.
- The source of truth is that golden set plus the market's own bar. The vendor's premium baseline sits in the race as the A0 column.
- Change the audience and the tier is re-derived, because what good means has flipped.
- One probe battery for everything. A category picks which rows gate and which merely report, and that pick is what defines the category. The direction of good is set per audience. A coffee ad reads gesture energy upward and a sleep ad flips the same instrument, because calm sells.
- 10 of the 11 named gating thresholds in [`probes/`](probes/) and [`gates/`](gates/) sit between a labelled pass and a labelled reject. The other 1 were typed by hand and the tool says so. A tool re-measures the shipped pixels and refuses to stay green if the number does not come back.
- I stay the final judge. A language-model judge attaches a blind description and a flag to the strip as evidence and never holds the verdict.

The race behind the router, with the probe readings, the winners per audience and what each engine's scenes cost, stays on the front page because the race ledger pins those tables by hash: see the README section of that name.
