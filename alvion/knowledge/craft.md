# Craft rules — non-negotiable

Every rule here was paid for with a rejected generation. They come from real client
work (EVOLV, Vantor, Water2, Cupids, Hero Bible, OROS) and from Krish's own notes.

## The script is sacred
- **Never change a word of the client script.** Not a synonym, not a trim, not a
  reorder. Every word must be spoken in some clip. If a clip cannot hold its words,
  split the clip — never the sentence mid-phrase.
- Alternate hooks each get their own clip and share every body clip.
- Mark every line with the clip that carries it. A line with no clip is a hole the
  editor will find in the edit, when it is expensive.

## Clips
- Plan scenes → shots → clips. One start-frame image per clip.
- Every clip is **at least 4 seconds**. 5–8s is the working range. **Never over 10s** —
  identity and background drift sharply past 10s on current models.
- Size each clip to its words, not a round number:
  Kling ≈ 3.3–3.7 words/sec, Seedance ≈ 2.5 words/sec (it ad-libs to fill slack).
- Add **1–2 seconds of silent handle** beyond the last word. A clip that ends on the
  final syllable is a hard cut the editor cannot fix.
- **Two locations = two clips.** Never ask one clip to transition between places.
- Fewer clips is better. Every clip is money and a stitch point.

## Shot coverage
- The classic failure is every shot medium, eye level, subject centred. Mix close-ups
  for reactions and details, a wide to establish, mediums for the rest, a few
  three-quarter or slightly low/high angles.
- Keep it shootable. No cameras inside fridges, not every shot a close-up.
- Camera height at chest/eye level and **level** — a tilted or high camera makes people
  look short and rooms look fake. Keep real-world scale: a bed, a door, a person.

## Continuity (the most common rejection)
- **The background must not change inside a clip.** Say it in every video prompt:
  static camera or handheld sway only, same room, same furniture, nothing added or
  removed, nothing leaves the frame.
- Objects held stay held for the entire clip. Glasses, bottles and papers vanish or
  float otherwise. Name the continuity: "she holds the bottle for the whole shot".
- Doors and fridges duplicate when a camera pans through them. Don't animate the door.
- Background extras must be alive and anatomically right — people who don't move read
  as dead.
- A character with nowhere to walk dissolves. Give them an exit in the frame.

## People
- Speaking faces are square to camera in the start frame, mouth fully visible,
  **resting pose** — not mid-gesture, not looking up or down.
- Eyeline: when the line is about the product, they look at the product; otherwise
  they hold the lens. Never glance left and right while delivering a line.
- Hands: exactly five fingers, real contact with what they hold. "Three hands" and
  "a hand coming out of his back" were both shipped by models and caught in review.
- Performance reads real when it is small: irregular blinks, micro-expressions,
  breathing, weight shifts, gestures that vary with the words and never loop.
  Fake smiles and staring eyes are the tell.
- Pace: UGC speech is **brisk**. Slow delivery was rejected repeatedly.

## Product truth
- The client's product image is the only reference. Never invent a feature, a
  window, a pump, a strip, a badge or a logo. Never guess the product from memory.
- Build a **product lock** first: one clean packshot from the real reference, then say
  "an exact faithful copy of the product reference" downstream. Long geometry
  descriptions make the model rebuild the product.
- Watch orientation — models mirror products constantly. State which side the cap,
  logo and label are on.
- **Keep labelled products at a natural distance.** Close to the lens, label text
  garbles and no prompt fixes it. Colours and the logo should read; words should not.
- Printed artwork degrades when a product rotates. Keep it square to camera or flat.
- Product in hand **before** its name is spoken, and visible in every cut after that.
- Product and person must look like one photograph. "Photoshopped on" and "pasted
  PNG" were both rejections — generate the product in the hand in the start frame.

## Claims
- Every claim traces to the brand's own information. Anything untraceable is cut at
  planning, not at legal review.
- Health, weight-loss, medical and timed-result claims are flagged: Meta and TikTok
  reject many even when the brand's site makes them. Show the result, don't state it.
- A generated person is a host or demonstrator. Never invent a customer testimonial
  attributed to a real person or a named creator.

## Credits
- One image per shot. One clip per shot. Regenerate only what fails.
- Images at 1K. Video at 720p for review and 1080p only when the edit is locked.
- Learn from each failure: a mistake caught in clip 2 must not repeat in clip 3.
