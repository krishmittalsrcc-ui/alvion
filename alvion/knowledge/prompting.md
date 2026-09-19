# Prompt construction

## The verify loop (run silently on every prompt before it is used)
Pass 1 — hard errors: identity lock identical in every product-touching prompt; no
product/brand words in video prompts (they get stamped on screen as text); product
preservation restated; no generated text anywhere; continuity seam described;
aspect ratio + photoreal stated; hook in the first 2s; every beat has action,
camera, light, pacing.
Pass 2 — simulate the model: harmonise vocabulary across prompts ("key light from
frame-left" everywhere, never "side light" in one); check physically impossible
handoffs; replace "it" with the named object; watch drift words ("floating",
"emerges", "orbiting"); strip words that trigger on-screen text ("label reads",
"wordmark"); run the muted-phone test; run the swap test.

## Image prompt (the start frame)
Flowing prose in this order: shot and angle · subject, body state, **full wardrobe
restated** · the t=0 resting pose · setting and what is on the surfaces · the product
as "an exact faithful copy of the product reference" plus orientation · light source
and quality · negatives.

Realism (images):
"Shot on an iPhone, natural window light with one side of the face slightly darker,
real skin texture with visible pores and small imperfections, no retouching, no
beauty smoothing, casual clothing wrinkles, a lived-in room with ordinary clutter,
slightly imperfect framing, everything in focus, no cinematic grade."
Studio product shots are the exception — clean light, but still real materials.

Known behaviours:
- Heavy characters get slimmed into bodybuilders: "NOT a bodybuilder, no V-taper, no
  defined pectorals, no muscle separation, no visible abs."
- Crew necks render as V-necks unless collar and chest graphic are separate features.
- Wardrobe drifts to the reference between shots — restate it every time.
- Describe fabric, never anatomy, when a body shape must show under clothing.
- One change per prompt. Two changes and one gets lost.
- To fix a small fault, **edit the approved image**: "Keep this photograph exactly the
  same. Change ONLY <one thing>. Do not alter pose, face, wardrobe, light, background
  or framing." To dial a detail, "change it slightly, about fifteen percent".

Standing image negatives:
`no subtitles, no captions, no on-screen text, no watermark, no logo overlay, no extra
limbs, no extra hands, exactly five fingers per hand, no duplicated subject, no floating
objects, no transparent or see-through product parts, no invented product features`

## Video prompt
Structure: what the shot is · IDENTITY LOCK · BACKGROUND LOCK · PRODUCT LOCK (if any) ·
timed action beats · camera · performance · DIALOGUE (verbatim) · negatives · duration.

Locks (verbatim, every clip):
- IDENTITY: "the same person in every frame, exactly as in the start image — must not
  become a different person, change age, skin tone, hair or build."
- BACKGROUND: "the room, furniture, walls, props and light stay exactly as in the start
  image for the entire clip; nothing is added, removed or rearranged; nothing leaves
  the frame."
- PRODUCT: "the product stays exactly as in the start image — same shape, colour,
  orientation and label; it is never re-lettered, enlarged or pushed toward the lens."

Dialogue (verbatim, every speaking clip):
"DIALOGUE — say exactly, word for word, once: "<line>". Do not rephrase, shorten, skip,
repeat or add words. The person on camera speaks every word; no voiceover. Starts
speaking within the first second. After the last word, holds still and silent for
about a second as a deliberate editing handle."
Spell hard words phonetically in brackets the first time (vaso-DIE-lation, EE-volv).

Realism (video — UGC):
"Handheld phone camera at arm's length, never locked off: continuous low-amplitude
sway, small corrective reframes, a one-to-two degree roll that settles. 26mm-equivalent
lens, mild edge distortion, one brief autofocus hunt, small auto-exposure shift, faint
rolling-shutter wobble. Irregular blinking, micro-expressions, visible breathing, small
nods, gestures that vary with the words and never loop. Face stays square to camera,
head rotation under ten degrees. Brisk, natural, conversational pace. Natural phone-mic
audio in a real room."
Polished/product shots: "Locked camera or one slow motivated move. Real materials,
real reflections, no CGI sheen."

B-roll: "No one speaks. No lip movement. Silent except natural ambience."

Standing video negatives:
`no subtitles, no captions, no on-screen text, no watermark, no lavalier or clip-on mic,
no mic wire, no headset, no earbuds, nothing clipped to clothing, no extra hands, no
morphing, no background change`

## End frames
- Default: start frame only. Two independently generated stills bookending a clip
  force the model to morph one room into the other.
- Pin an end frame only when it is an **edit of the start frame** (same room). Use it to
  hold a framing, to finish an action (garment fully on), or to guarantee a clean
  silent tail on a dialogue clip.
- Pin a resting face-to-camera pose, never a mid-action one.
