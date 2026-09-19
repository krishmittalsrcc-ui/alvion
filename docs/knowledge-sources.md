# Where ALVION's knowledge comes from

Everything the planner, router, QC and editor do is traceable to one of four sources. The
rules themselves live in `alvion/knowledge/*.md` and are injected into every Claude call.

## 1. Krish's own production history (36 Claude Code sessions, Aug–Sep 2026)

437 messages across real client jobs — EVOLV V-Boost (FG011/020/024/027/031/034,
AR229/232), Vantor, Water2, Cupids Hypnosis, Hero Bible, OROS, Soft Landings — plus the
distilled memory notes from those jobs. The recurring rejections became rules and, where
measurable, automated checks:

| Rejection (his words, paraphrased) | Became |
|---|---|
| "The background is changing" — the most frequent note | BACKGROUND LOCK in every video prompt + **edge-drift QC** |
| "Don't change a single word of the script" | Exact-script mode, **plan coverage check**, **Whisper script-diff QC** |
| "Very hard cut — add 1–2 seconds" | 1–2s silent handles in planning + **tail-handle QC**; "hard cut" feedback auto-extends the clip |
| Mic on his chest / three hands / hand out of his back | Standing video negatives; flagged for human review |
| Bottle too close — label garbles | "Keep labelled products at a natural distance" rule |
| Product looks Photoshopped on / pasted PNG | Product generated in-hand in the start frame; product lock |
| Speaking too slowly / fake smile / eyes unnatural | Brisk pace + micro-expression performance block |
| All the same camera angle | Shot-coverage rule |
| Glass vanishes / bottle floats / fridge has two doors | Continuity rules per object |
| Don't repeat a mistake from clip 2 in clip 3 | **Per-video lessons**: every piece of feedback is appended to later generations |
| Add a filter/texture so it feels real; smoother cuts | Look presets + J-cuts + per-cut audio fades |
| One image, one clip; save credits | One-per-shot pipeline, 1K images, 720p review video |

His own realism prompt (handheld iPhone sway, autofocus micro-hunt, rolling-shutter wobble,
gestures that never loop, head rotation under 10°) is the UGC realism block verbatim.

## 2. His Claude skills

| Skill | Used for |
|---|---|
| `alvion-prompt-verify-loop` | The two-pass verify loop run on every prompt |
| `hook-engine` | Ten attention mechanisms; `hook_mechanism` in every plan |
| `film-story-architecture` | Situation → complication → turn → residue; the cost sentence |
| `category-physics` | Category line in every plan; per-category hook and proof rules |
| `kill-room` | The 8-axis score, default-3 discipline, rebuild thresholds |
| `sound-design-engine` | Music enters late, one silence beat, sound before picture |

By creation date the two most recently added skills are `canvas-design` and
`brand-guidelines` (Anthropic defaults, 14 Sept). `brand-guidelines` applies Anthropic's
own colours and fonts, so it has no place in client ad work. `canvas-design` is a
candidate for future static thumbnails and cover frames, and is not used yet.

## 3. Web research (Sept 2026)

| Finding | Where it went | Source |
|---|---|---|
| Post order for AI footage: light blur → fine grain → grade; blur after grain smears it back to plastic; grain "smaller than you expect"; keep denoise low | `LOOKS` in editor.py | [invideo — AI video post-production](https://invideo.io/blog/ai-video-post-production/), [invideo — grain & blur](https://invideo.io/faq/does-adding-film-grain-and-blur-to-ai-generated-video/) |
| Realism is requested as camera defects (focus hunting, exposure shift, imperfect framing), pores and imperfections, messy mixed light | Realism blocks in prompting.md | [Atlabs — realistic AI UGC](https://www.atlabs.ai/blog/create-realistic-ai-ugc-videos-complete-guide), [Luma — realistic prompts](https://lumalabs.ai/news/prompt-realistic-ai-videos), [videoai.me — iPhone look](https://videoai.me/blog/how-to-make-ai-videos-that-look-filmed-on-iphone) |
| 5ms fades hide a cut; >50ms blurs dialogue; J-cuts pull the viewer forward; room tone mismatch reveals cuts | 8ms edge fades, J-cut prelap, edit.md | [Descript — crossfades](https://www.descript.com/blog/article/crossfade-audio-what-crossfade-is-and-how-to-edit-it), [CapCut — J/L cuts](https://www.capcut.com/create/j-cuts-and-l-cuts-dialogue-edits) |
| Cut pauses first; micro-cuts early; change every 3–5s; punch-ins on emphasis | Fast/tight pacing, punch-ins | [NoteGPT — short-form editing](https://notegpt.io/guides/how-to-edit-a-video), [Maken Media](https://maken.media/blog-short-form-editing) |
| −14 LUFS integrated / −1 dBTP; platforms turn hot masters down | Two-pass loudnorm | [TrackGleam — LUFS for shorts](https://trackgleam.com/learn/master-for-tiktok-reels-shorts), [Mr. Vocal](https://mrvocal.com/posts/loudness-for-shorts) |
| TikTok hides ~320px bottom / ~120px right; Reels ~420px bottom, ~220px top | `SAFE_MARGIN_V` per platform | [Kreatli — safe zones](https://kreatli.com/guides/safe-zone-guide), [House of Marketers](https://houseofmarketers.com/guide-to-safe-zones-tiktok-facebook-instagram-stories-reels/) |

## 4. Model research (Sept 2026) — why each role gets the model it does

The router in `alvion/router.py` scores every model in `alvion/catalog.py` on the strengths
below. Prices and parameters come from Higgsfield itself (`models_explore` and `get_cost`,
Sept 19 2026). Quality claims come from Krish's own results plus these comparisons:

| Finding | Where it went | Source |
|---|---|---|
| Kling 3.0: phoneme-level lip sync per character, strong human motion, best value (~$0.84 per 10s at 1080p with audio) | Default for **talking shots** | [buildfastwithai — Seedance 2.5 vs Veo 3.1 vs Kling 3.0](https://www.buildfastwithai.com/blogs/seedance-2-5-vs-veo-3-1-vs-kling-3-0-best-ai-video-2026), [SeaVerse — Kling 3.0 vs Veo 3.1](https://seaverse.ai/features/kling-3-0-vs-veo-3-1-comparison) |
| Seedance is best at combining your own reference images, video and audio; 2.5 does native 30s clips; practical top pick for realistic UGC shorts | Default **B-roll** when references matter; product and silent ads | [3DAI Studio — best AI video generator 2026](https://www.3daistudio.com/blog/best-ai-video-generator-2026), [Krea — best models for UGC shorts](https://www.krea.ai/blog/the-5-best-ai-video-models-for-ugc-shorts-in-2026) |
| Veo 3.1: realism and native audio (lip sync ~120ms); premium polish; Lite tier among the cheapest credible options | **Cinematic** and **explainer**; Veo 3.1 Lite in budget mode | [Pixo — Seedance vs Veo vs Kling](https://pixo.video/blog/seedance-vs-veo-vs-kling), [Lushbinary — 2026 comparison](https://lushbinary.com/blog/ai-video-generation-sora-veo-kling-seedance-comparison/) |
| Gemini Omni Flash leads Artificial Analysis' audio-video ranking, Seedance second | In the B-roll list; always generates audio, so the edit mutes it | [Krea — best models for UGC shorts](https://www.krea.ai/blog/the-5-best-ai-video-models-for-ugc-shorts-in-2026) |
| Hailuo 2.3 wins on affordability; strong motion and emotion | Default for **dance / motion** | [buildfastwithai](https://www.buildfastwithai.com/blogs/seedance-2-5-vs-veo-3-1-vs-kling-3-0-best-ai-video-2026), [Hailuo — Seedance vs Kling vs Sora](https://hailuoai.video/pages/blog/seedance-vs-kling-vs-sora) |
| Veo for talking, Kling for long multi-shot, Seedance for references | Cross-check on the three roles | [Yangsweb — Veo vs Kling vs Seedance](https://www.yangsweb.com/blog/veo-vs-kling-vs-seedance-comparison-2026) |

Where Krish's own results disagree with the reviews, his results win: Kling for avatars
and talking heads, a motion model for dance, Soul for realistic UGC people with no
reference, GPT Image 2 whenever a product reference has to be followed exactly.

**What `models_explore` is not.** Higgsfield's own "recommend" mode matches keywords, not
quality, so ALVION uses it only for parameter names and never for picks.

## What is measured versus what is not

ALVION measures: background drift, spoken words against the script, silence handles,
speech timing, loudness, format. It **cannot** hear voice quality or judge lip sync, hands
or physics — those stay with the human reviewer, and the UI says so at every review step.
