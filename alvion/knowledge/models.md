# Model behaviour — learned on real jobs

Routing is automatic (router.py); these rules shape the prompts for whichever model
the router picks.

## Kling (avatar, UGC, talking heads)
- Best faces, lip movement and human motion.
- Drops identity on long clips (a man became someone else from ~4s in an 8s clip).
  Keep dialogue clips ≤ 8s, or pin an end frame that is an edit of the start frame.
- Degrades printed artwork when an object rotates — keep products square to camera.
- Always adds a logo to a plain navy polo. Pick another garment or pin a clean end frame.
- Hallucinates clip-on mics on talk-to-camera shots — always negate.

## Seedance (B-roll, motion, product in hand)
- Ad-libs when the clip is longer than the script — size duration to ~2.5 words/sec
  and say "speaks the line ONCE, never repeats a phrase, never says the name twice".
- Rejects some reference images as NSFW that other models accept — pass the product as
  the start image rather than as an extra reference.
- Rejects some child framings; hands-only framing passes and usually looks better.
- Places lines across cuts on its own judgement — keep the product visible in every
  cut once it is introduced.

## Veo (dialogue with native audio, cinematic)
- Generates speech inside the clip. First+last-frame variant pins handles.
- Expensive — draft tier uses the Fast variant.

## Omni Flash / fast video models
- Audio is always generated — say "no speech, no music, only ambience" for B-roll and
  mute it in the edit.
- Sometimes ignores the aspect ratio — state "vertical 9:16" in the prompt as well.
- Objects vanish mid-shot, long props stretch in place, set-down props float. Name the
  continuity ("the paper slides as one solid sheet, it must not stretch").

## Image models
- GPT Image 2: best general photoreal and text rendering; refuses swimwear references
  and some body-shape prompts — describe fabric, not anatomy; edit an approved image
  rather than regenerating.
- Seedream: accepts references GPT Image 2 refuses; natural "de-slopped" look.
- Soul Reference / Character: when a product or person must match an upload.

## All models
- Preset interception on submission is not a charge — resubmit with the preset declined.
- A credit balance is not a receipt. Check the job list before resubmitting after an error.
- Queued is normal on a shared plan. Never resubmit a queued job.
