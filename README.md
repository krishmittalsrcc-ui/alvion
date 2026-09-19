# ALVION

**Brief in. Finished ad out.**

ALVION is a standalone web product that automates AI ad video generation end to
end. You fill in a form — what kind of video, what ratio, the script, the brand,
your instructions — and it plans the ad, writes every prompt, generates the
frames and the clips, measures them, cuts the video, burns in captions, scores it
with music, and hands you a finished vertical MP4.

It stops exactly once: before it spends anything, to show you the bill.

- **Planning** runs on Claude (`claude-opus-5` by default), through your Anthropic account.
- **Generation** runs on your own Higgsfield account — Kling, Seedance, Veo, Gemini Omni,
  Hailuo, Wan, Cinema Studio, Soul, GPT Image, Nano Banana, Seedream — through
  Higgsfield's MCP server, connected with a one-click sign-in.
- **Editing** runs locally on ffmpeg.

It runs on your machine today and is built as a multi-user SaaS foundation —
accounts, per-user encrypted credentials, per-user job isolation and credit
ceilings — so selling seats later is a bolt-on, not a rewrite.

---

## Run it

```bash
cd ~/alvion
python3 -m pip install --user -r requirements.txt
./run.sh
```

Open <http://127.0.0.1:8080>, create an account (the first account is the admin),
then connect Higgsfield and Anthropic under **Connections**.

With no keys it still runs: planning falls back to a local planner and generation
uses a built-in mock provider, so you can drive the whole pipeline offline and
for free before spending a credit.

### Connect your accounts — no keys to copy

**Connections** has two sign-in buttons. Neither asks you for a key.

| Button | What happens | Used for |
|---|---|---|
| **Continue with Higgsfield** | A popup opens Higgsfield's own sign-in (Google, Apple, Microsoft or email). If you are already signed in to higgsfield.ai in that browser, you only click **Allow**. The popup closes itself and your balance appears. | Every image and clip, billed to your own Higgsfield credits |
| **Sign in with Anthropic** | ALVION installs Anthropic's official `ant` CLI (checksum-verified), then opens Anthropic's sign-in in your browser. Approve it and ALVION picks the connection up by itself. *Open it in a popup instead* gives you a code to paste back. | The planner |

How it works underneath:

- **Higgsfield** is standard OAuth 2.1 with PKCE against Higgsfield's MCP server
  (`mcp.higgsfield.ai`, authorised by `clerk.higgsfield.ai`). ALVION registers itself as a
  client, never sees your password, and stores only the access and refresh tokens —
  encrypted — in `data/`. Refresh is automatic; **Disconnect** deletes them.
- **Anthropic** uses the official `ant auth login` flow; the SDK reads that profile
  directly. An Anthropic **API key** still works as a fallback (*Use an API key
  instead*). A Claude.ai Pro/Max subscription cannot be connected to a third-party app —
  Anthropic does not allow it — so the planner bills your Anthropic API account.

With nothing connected it still runs end to end: the offline planner and the free mock
generator stand in, so you can try every step before spending a credit.

---

## How it's organised

```
Brand                 product facts + reusable assets (logos, product shots, characters)
 └── Project          a folder of videos — one campaign, one launch, one client batch
      └── Video       one ad, planned and generated end to end
```

Brand assets are uploaded once and attach to every frame ALVION generates for that
brand, so the product and the character stay consistent across a whole campaign.
The **Library** shows every video you have made, newest first.

## Making a video — three questions

1. **What kind of video?** Avatar, UGC, product demo, cinematic, dance/motion,
   voiceover explainer or silent. This one answer decides the models and the structure.
2. **The idea.** A script, or just a description. Tap any brand assets to attach.
3. **Models & format.** ALVION has already picked a model for each kind of shot, with
   the price beside it. Keep it, or tap the card and choose another. Then quality
   (720p or 1080p — the prices update as you switch), ratio, platform and length.

Then ALVION plans everything and shows you the bill.

## It suggests the models — you can switch any of them

`alvion/router.py` splits every ad into up to three **roles** and suggests the best model
for each, from a curated catalogue of Higgsfield models (`alvion/catalog.py`) with their real
parameters and prices:

| Role | What it covers |
|---|---|
| **Talking shots** | Anyone speaking on camera, with the voice generated in the clip |
| **B-roll** (or **Shots** when nobody talks) | Cutaways, product shots, motion |
| **Frames** | The start image of every shot |

What it suggests by default (prices are Higgsfield credits per 5s at 720p / 1080p, from
Higgsfield's own `get_cost` quotes, Sept 2026):

| Kind of ad | Talking | B-roll / shots | Frames |
|---|---|---|---|
| Avatar, UGC | **Kling 3.0** (10 / 12.5) — per-phoneme lip sync, best value | **Seedance 2.5** (35 / 60) — best with your references | **Soul 2.0** (0.12) |
| Product demo | — | **Seedance 2.5** | **GPT Image 2** (3.5 / 6.5) |
| Cinematic, explainer | — | **Veo 3.1** (13.8 / 25) — realism, native audio | GPT Image 2 |
| Dance / motion | — | **Hailuo 2.3** (6 / 8.3) — motion and emotion | GPT Image 2 |
| Silent | — | **Seedance 2.5** | GPT Image 2 |

**Budget mode** makes price count more: B-roll moves to Seedance 1.5 Pro (10 / 15) or
Veo 3.1 Lite (7.5, 720p only), frames to GPT Image 2.5.

Also in the catalogue: Kling 3.0 Turbo, Gemini Omni Flash 1.1, Wan 3.0, Cinema Studio 3.0,
Nano Banana Pro and Seedream 5.0 Pro.

**Switching.** Each role is a card. Tap it and a Higgsfield-style menu lists every model
that can do that job — its tags (audio, end frame), what it is best at, what to watch for,
and its price at the chosen quality — with ALVION's suggestion marked. You can switch:

- **before planning**, in the *Models & format* step;
- **for the whole video**, on the plan page (model cards and the 720p/1080p switch);
- **for one shot**, with the model chip on any shot card. If that shot already has a clip,
  switching regenerates it on the new model (the old version moves to `_superseded/`).

Every choice comes with its reasons in plain English. When you override a suggestion, the
reason says so (*Your pick; ALVION suggested Seedance 2.5*).

**Per-model handling.** `catalog.build_video_params` maps each shot onto what that model
accepts: its own duration steps (Veo 4/6/8s, Seedance 1.5 4/8/12s — talking shots always
round **up** so the line is never cut), its resolution flag (Kling `std`/`pro`, others
`720p`/`1080p`), its audio switch, and whether it takes an end frame. Talking shots pin
the start frame as the end frame when the model allows it, which leaves a clean silent
tail for the cut.

The research behind the suggestions is in `docs/knowledge-sources.md`.

## The workflow — you approve every expensive step

```
 1  Assets + script ─► PLAN        Claude splits the script into shots, scores the concept
                                   (kill room), picks the models, writes every prompt.
 2  ─► IMAGES   one start frame per shot. Approve each, or type a change — ALVION edits
                that image and keeps everything else. Feedback becomes a lesson for later shots.
 3  ─► CLIPS    each clip is QC'd automatically (background drift, spoken words vs script,
                cut handles, format) and flagged for your review. Approve or request changes.
 4  ─► EDIT     a few questions: captions, pacing, look, cuts, platform, music.
 5  ─► RENDER   finished MP4 + optional textless copy for CapCut. Change an answer, re-render.
```

Cost is shown and confirmed before images and again before clips. Nothing paid is ever
deleted — superseded versions move to `_superseded/`.

## Automated QC (qc.py)

| Check | Catches |
|---|---|
| Edge drift — frame borders vs the first frame | The background changing mid-clip |
| Whisper transcript vs approved line | Dropped, added or repeated words |
| Head/tail silence | Hard cuts that end on the last syllable |
| Format | Models ignoring the aspect ratio |

## The editor (editor.py)

Trims on measured speech · jump cuts on pauses with alternating punch-ins · J-cuts (sound
~8 frames before picture) · 8ms fades on every cut · optional crossfades at clip boundaries ·
word-by-word captions timed by Whisper but **spelled from the approved script** · captions
placed in each platform's safe zone · generated music that enters after the hook, ducks under
voice and drops out for one silence beat · blur → grain → grade look presets · two-pass
loudness to −14 LUFS / −1 dBTP.

Where all of this comes from — your sessions, your skills, and the web research, with
sources — is in [`docs/knowledge-sources.md`](docs/knowledge-sources.md).

## Why the output is usable

The difference between this and a generic wrapper is that the craft rules are
written down and injected into the planner on every call
(`alvion/knowledge/`). Each one exists because breaking it produced a failed,
paid-for generation:

- Every clip is at least 4 seconds; durations are the real spoken length as
  integers, never rounded up to a 5/10 ladder — about a third of the spend on a
  twelve-clip ad.
- Dialogue clips carry 12–18 words at 3.3–3.7 words per second.
- A talking clip pins its start frame as its end frame. That, not prompt wording,
  is what produces silent handles the edit can actually cut on.
- Speaking characters face the lens in a resting pose; a mid-action pinned frame
  freezes the body while only the head swivels.
- Heavy characters get explicit negatives or the image model slims them into
  bodybuilders. A crew neck renders as a V-neck unless the collar and chest
  graphic are described separately.
- Standing negatives on every video prompt, including the clip-on mic that
  otherwise appears on talk-to-camera shots.
- Shot coverage is varied on purpose — the classic failure is every shot medium,
  eye level, centred.
- Claims are traced to the brand text you supply and flagged when a platform is
  likely to reject them.

Cuts are made from **measurement**, not guesses: head/tail silence per clip,
speech/pause maps, captions timed to real speech onsets.

---

## Layout

```
alvion/
  main.py             FastAPI app and API (62 routes)
  catalog.py          the Higgsfield model catalogue: params, durations, audio, frames, prices
  router.py           suggests a model per role, ranks the alternatives, explains why
  hf_mcp.py           Higgsfield OAuth (PKCE + dynamic client registration) and MCP client
  claude_connect.py   the official `ant` CLI: install, sign-in, profile
  brain.py            Claude planner, prompt revision, edit defaults
  worker.py           the staged pipeline (plan → images → clips → edit)
  qc.py               automated clip checks
  editor.py           the edit and render
  media.py            ffmpeg primitives — probe, silence, music
  db.py security.py   SQLite, passwords, Fernet credential encryption
  providers/          higgsfield_mcp.py (live, your account) · mock.py (offline)
                      higgsfield.py — the Higgsfield Cloud developer API, kept for a
                      hosted build; not used by default
  knowledge/          craft · story · prompting · models · edit
  web/                UI (no build step), Lucide icons, Unsplash imagery (CREDITS.json)
docs/                 knowledge-sources.md
data/                 SQLite, master key, OAuth client, tokens, uploads, job media (gitignored)
```

### Keeping the catalogue current

Higgsfield adds models often. To add or re-price one, edit `alvion/catalog.py`: copy an
entry, fill in the parameter names from Higgsfield's `models_explore`, and take prices from
a `get_cost` quote. The router, the picker and the cost gate all read from it. Once you are
connected, the cost modal's **Get Higgsfield's exact quote** asks Higgsfield for the live
price of every shot before you approve.

---

## API

Everything the UI does is a plain HTTP call, so the whole thing is automatable.

```
POST /api/auth/register | /api/auth/login | /api/auth/logout
GET  /api/me                          POST /api/me
POST /api/credentials                 DELETE /api/credentials/{provider}
GET  /api/brands                      POST /api/brands
GET  /api/brands/{id}                 POST /api/brands/{id}
POST /api/brands/{id}/assets          POST /api/brands/{id}/links
GET  /api/brand-assets/{id}/file      DELETE /api/brand-assets/{id}
GET  /api/projects                    POST /api/projects
GET  /api/projects/{id}               POST /api/projects/{id}/videos
GET  /api/intents                     POST /api/router/preview
GET  /api/videos                      GET  /api/videos/{id}
GET  /api/videos/{id}/events?after=N  GET  /api/videos/{id}/asset/{asset_id}
POST /api/videos/{id}/approve         POST /api/videos/{id}/replan | /cancel

GET  /oauth/higgsfield/start          GET  /oauth/higgsfield/callback
GET  /api/connect/status              GET  /api/higgsfield/balance
POST /api/connect/claude/install      POST /api/connect/claude/login   {mode: browser|popup}
POST /api/connect/claude/code         GET  /api/connect/claude/poll
GET  /api/catalog                     POST /api/router/preview         {video_kind, resolution, models}
POST /api/videos/{id}/models          {talking, broll, frames, resolution}
POST /api/videos/{id}/shots/{sid}/model  {model}
POST /api/videos/{id}/quote           live get_cost for every shot
POST /api/videos/{id}/shots/{sid}/clip/revise  {feedback?, model?}
```

---

## Turning this into a SaaS

The schema is already multi-tenant. What still has to be built:

| Step | Notes |
|---|---|
| Billing | Stripe against `users.plan`; `credit_ceiling` is already enforced at the gate |
| Hosting | The worker needs a long-running host — Fly, Railway, a container. A serverless function cannot hold a render |
| ffmpeg on Linux | The bundled binary is macOS; a Linux image needs its own |
| Object storage | `data/jobs/` becomes S3 or R2 |
| Queue | Threads are fine for one operator; multiple tenants want a real queue |
| Secrets | Fernet with a local master key is right for local; hosted wants a KMS |
| Higgsfield sign-in | Works hosted as-is: the OAuth client is registered per redirect URI, so a real domain gets its own client on first use |
| Anthropic sign-in | The `ant` CLI profile is per machine, so hosted customers connect with an API key — or ALVION plans on its own key and bills for it |

None of that changes the pipeline — only where it runs and who may start one.

---

## Known limits

- Catalogue prices are Higgsfield's own quotes from Sept 2026. Higgsfield re-prices
  models; use **Get Higgsfield's exact quote** before a big batch, and update
  `catalog.py` when the numbers move.
- Live generation through Higgsfield's MCP has been built against its published tool
  contract but not yet run on a real account. The first connected run is the real test.
- The Higgsfield sign-in needs a normal browser window. Some embedded browsers open the
  popup in the same tab; it still works, it just does not close itself.
- ALVION measures duration, resolution and silence. It cannot hear audio or judge
  lip sync, and it says so on every delivery. Check those on playback.
- The offline fallback planner produces a runnable plan, not a good one. The
  Claude planner is the product.
