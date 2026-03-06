---
name: cover
description: Design and generate a book cover. Use when the author wants to create, refine, or regenerate their cover image — from Claude-designed SVG artwork to AI-generated illustrations with text compositing.
---

# Storyforge Cover Design

You are designing a book cover with the author. A great cover sells the book before a single word is read. This skill supports two tiers of cover creation — Claude-designed SVG artwork (always available) and AI-generated illustrations (with an API key) — and integrates with the existing production pipeline.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Before doing anything else, orient yourself:

1. **Read `storyforge.yaml`** — title, genre, subgenre, logline, phase, coaching level.
2. **Read `reference/chapter-map.yaml`** (if it exists) — check `production.cover_image`, `production.cover.subtitle`, `production.cover.palette`, `production.author`.
3. **Read key reference documents** for visual inspiration (all that exist):
   - `reference/story-architecture.md` — themes, central conflict, premise, structure
   - `reference/character-bible.md` — protagonist details, imagery, defining traits
   - `reference/world-bible.md` — setting, atmosphere, visual world, sensory details
   - `reference/voice-guide.md` — tone, mood, register
4. **Read the key decisions file** — check for any existing cover-related decisions.
5. **Check for existing covers** in `manuscript/assets/` — `cover.png`, `cover.svg`, `cover-illustration.png`.

## Step 2: Detect Capabilities

Before determining mode, check what tools are available:

1. **Image generation APIs** — check for `OPENAI_API_KEY` and `BFL_API_KEY` environment variables using the Bash tool.
2. **PNG conversion** — check for `rsvg-convert` (best quality) and `sips` (macOS fallback) using the Bash tool. **At least one must be available.** If neither is found, tell the author: "Cover design requires a PNG converter. Install librsvg (`brew install librsvg`) and try again." Then stop — do not proceed without a way to produce the final PNG.
3. **Cover fonts** — check that the recommended cover fonts are installed. These are free Google Fonts that `rsvg-convert` needs at render time. Without them, SVG text falls back to generic serif/sans-serif and the cover will look wrong.

   Run this check using the Bash tool:
   ```bash
   missing_fonts=()
   for font in "Playfair Display" "Cormorant Garamond" "EB Garamond" "Oswald" "Bebas Neue"; do
       if ! fc-list : family 2>/dev/null | grep -qi "$font"; then
           missing_fonts+=("$font")
       fi
   done
   if [[ ${#missing_fonts[@]} -gt 0 ]]; then
       echo "MISSING FONTS: ${missing_fonts[*]}"
   else
       echo "All cover fonts installed."
   fi
   ```

   If `fc-list` is not available, tell the author: "Install fontconfig to check fonts: `brew install fontconfig`"

   If fonts are missing, tell the author which ones and how to install them:
   > "Your system is missing these cover fonts: **{list}**. Install them to get the best results. All are free Google Fonts — download from [fonts.google.com](https://fonts.google.com) and install via Font Book, or use Homebrew:
   > ```
   > brew install --cask font-playfair-display font-cormorant-garamond font-eb-garamond font-oswald font-bebas-neue
   > ```
   > I can proceed with fallback fonts, but the cover may not match the intended design."

   Let the author decide whether to install now or proceed with fallbacks. Do not block — missing fonts degrade quality but don't prevent cover generation.

4. **Store capability flags** for use in mode determination:
   - **Tier 1 (SVG Design)**: Available if `rsvg-convert` or `sips` is installed. Claude composes SVG, then converts to PNG.
   - **Tier 2 (AI Image Generation)**: Available if `OPENAI_API_KEY` or `BFL_API_KEY` is set.
   - **Compositing**: Available if Tier 2 is available AND `rsvg-convert` is installed (sips cannot render SVG with embedded raster images).

## Step 3: Determine Mode

Based on the author's message and project state:

---

### New Cover

No cover exists, or the author explicitly asks to create one.

1. Present available tiers based on detected capabilities:
   - Always: "I can design a custom SVG cover for your book — layered artwork with gradients, textures, and symbolic imagery drawn from your story."
   - If Tier 2 available: "I can also generate a photographic or illustrated cover using AI image generation, with your title composited as crisp text on top."
2. Recommend the best available option. If Tier 2 is available, mention both and let the author choose.
3. Route to the chosen tier's workflow below.

---

### Refine Cover

Cover exists. Author wants to adjust it.

1. Read the existing cover files to understand what was produced.
2. If SVG exists: load it, discuss what to change, iterate.
3. If only a raster image exists: ask whether the author wants to redesign from scratch or adjust the text overlay.

---

### Replace Cover

Author has their own cover image (external file).

1. Accept the file path from the author.
2. Verify the file exists.
3. Copy or reference the file in `manuscript/assets/`.
4. Update `production.cover_image` in `reference/chapter-map.yaml`.
5. Commit and push.

## Tier 1: Claude-Designed SVG Covers

This is the core capability. You are composing original artwork in SVG, not generating boilerplate.

### Step T1.1: Analyze the Story for Visual Themes

Synthesize from the reference documents read in Step 1:

- **Central visual metaphor** — what single image captures this story? A door, a key, a mirror, a road, a crown, a wound, a flame? Find the image that is *this story* and no other.
- **Color mood** — dark/light, warm/cool, saturated/muted. What does the genre expect? What does the story's tone demand?
- **Genre conventions** — what do covers in this genre look like? What visual signals tell a reader "this is a thriller" or "this is literary fiction"?
- **Symbolic elements** — objects, settings, motifs that recur in the story. These are your raw materials.
- **Typography feel** — bold/delicate, modern/classical, serif/sans-serif. The title treatment is half the cover.

### Step T1.2: Propose a Cover Concept

Present a brief "cover concept" to the author — one paragraph describing the visual direction:

> "Your story is a dark literary thriller about memory and identity. I'm thinking: a deep navy-to-black gradient background, a fragmented mirror motif using SVG clip-paths, your title in a clean condensed serif with wide letter-spacing and a hairline weight, and a thin gold accent line. The overall feel: elegant, unsettling, restrained."

Ask the author if the concept resonates, or if they want to push in a different direction. Iterate on the concept before generating SVG. This is a conversation, not a quiz.

### Step T1.3: Compose the SVG

Write the SVG file to `manuscript/assets/cover.svg` using the Write tool.

**Dimensions:** 1600×2400 pixels (standard 2:3 book cover ratio).

**Layer structure** — build the cover in layers, bottom to top:

1. **Background** — rich gradient (linear, radial, or layered). Never a flat solid color.
2. **Texture/atmosphere** — `feTurbulence` for organic noise, geometric patterns, grain overlays, subtle tonal variation.
3. **Imagery/motif** — the central visual element. Use clip-paths, masks, shapes, and symbolic SVG artwork to create the cover's defining image.
4. **Text** — title, subtitle, author name. This is the most important layer.
5. **Overlay effects** — vignetting, edge gradients, accent lines, decorative elements.

**SVG techniques to use:**

- **Gradients**: `<linearGradient>`, `<radialGradient>` with multiple stops for rich color transitions. Layer multiple gradients using opacity for depth.
- **Filters**: `<feGaussianBlur>` for depth-of-field. `<feColorMatrix>` for tinting. `<feTurbulence>` + `<feDisplacementMap>` for organic texture. `<feComposite>` for blending.
- **Clip-paths and masks**: `<clipPath>` for silhouettes and window effects. `<mask>` for soft-edge reveals and fragmented compositions.
- **Shapes and paths**: `<path>` for custom curves and shapes. `<polygon>` for geometric forms. Combine with transforms (`translate`, `rotate`, `scale`) for dynamic layouts.
- **Text**: `<text>` elements with `text-anchor="middle"` for centering. Use `letter-spacing`, `font-weight`, `font-size` attributes. Stack font families for fallbacks.
- **Opacity and blending**: Use `opacity` on groups. `mix-blend-mode` for layer interactions (where supported).

**Design philosophy — make it UNFORGETTABLE:**

- **Commit to a bold aesthetic direction.** Not safe, not generic, not forgettable. Every cover should have one thing someone will remember.
- **Distinctive typography.** Do not default to Georgia or Arial. Use font stacks that suggest character: `'Playfair Display', 'Palatino Linotype', 'Book Antiqua', serif` for literary elegance. `'Oswald', 'Bebas Neue', 'Impact', sans-serif` for bold thrillers. `'Cormorant Garamond', 'Garamond', 'EB Garamond', serif` for refined warmth. The font IS the brand.
- **Dominant colors with sharp accents.** A cover with one bold color and one accent beats a timid, evenly-distributed palette every time.
- **Unexpected spatial composition.** Asymmetric title placement. Text overlapping the imagery. Generous negative space OR controlled density. Not everything centered in the safe zone.
- **Atmosphere and depth.** Gradient meshes, noise textures, geometric patterns, layered transparencies, dramatic shadows. A flat cover is a dead cover.

**Title sizing** — follow this logic for readability:

| Title length | Font size | Max chars per line |
|---|---|---|
| ≤8 chars | 140px | 12 |
| 9-15 chars | 120px | 12 |
| 16-25 chars | 96px | 16 |
| 26-40 chars | 72px | 22 |
| >40 chars | 56px | 30 |

Break titles at word boundaries. Center each line. Space lines at font-size + 20px.

**Author name:** Position in the lower portion of the cover. Typically 36-48px, with generous letter-spacing (6-10px). All caps or small-caps often works well.

### Step T1.4: Preview and Iterate

Tell the author: "I've saved the SVG cover to `manuscript/assets/cover.svg`. Open it in your browser to preview — it renders natively in any modern browser."

Ask if they want adjustments. Iterate as needed — each iteration overwrites the SVG file. Common adjustments:
- Color shifts
- Typography changes (font, size, weight, spacing)
- Motif refinement
- Layout repositioning
- Adding or removing elements

### Step T1.5: Convert to PNG

Once the author approves, convert the SVG to PNG. **The cover skill must produce a PNG** — downstream processes (epub generation, production pipeline) expect `cover.png` and should never need to convert formats themselves.

Before attempting conversion, check that a converter is available. If neither tool exists, **stop and tell the author to install librsvg** — do not proceed without a PNG.

```bash
mkdir -p manuscript/assets
if command -v rsvg-convert >/dev/null 2>&1; then
    rsvg-convert -w 1600 -h 2400 -o manuscript/assets/cover.png manuscript/assets/cover.svg
elif command -v sips >/dev/null 2>&1; then
    sips -s format png -z 2400 1600 manuscript/assets/cover.svg --out manuscript/assets/cover.png 2>/dev/null
else
    echo "ERROR: No PNG conversion tool available."
    echo "Install librsvg for best results: brew install librsvg"
    exit 1
fi
```

**After conversion, verify the PNG was produced and is non-empty:**

```bash
if [[ ! -s manuscript/assets/cover.png ]]; then
    echo "ERROR: PNG conversion produced an empty or missing file."
    echo "Install librsvg for reliable conversion: brew install librsvg"
    exit 1
fi
echo "Cover PNG verified: $(wc -c < manuscript/assets/cover.png) bytes"
```

Do not move to the next step until `cover.png` exists and is valid.

### Step T1.6: Update Configuration and Commit

1. Update `production.cover_image` in `reference/chapter-map.yaml` (if it exists) to point to the cover file.
2. Commit and push:
```
git add -A && git commit -m "Cover: design custom SVG cover for {title}" && git push
```

## Tier 2: AI Image Generation

Available when `OPENAI_API_KEY` or `BFL_API_KEY` is set.

### Step T2.1: Craft the Image Prompt

Synthesize a detailed image generation prompt from project state. Build it systematically:

- **Style/medium**: "Digital illustration," "Oil painting style," "Cinematic photograph," "Watercolor," "Art deco poster," etc. Match the genre and tone.
- **Scene/composition**: What the image depicts — not the book's plot, but a single evocative visual moment or symbol.
- **Mood/atmosphere**: Lighting, color temperature, emotional tone, time of day.
- **Genre conventions**: What covers in this genre typically show.
- **Technical**: Aspect ratio, color palette guidance.

**CRITICAL**: The prompt must explicitly state "no text, no letters, no words, no typography." AI text rendering is unreliable. Title and author text will be composited separately as crisp SVG.

### Step T2.2: Author Reviews the Prompt

Present the full prompt to the author before spending API credits. This is their money — let them refine it. Common adjustments:
- Tone shifts ("darker," "more hopeful," "less literal")
- Composition changes ("tighter crop," "more negative space")
- Style pivots ("more painterly," "more photographic")

### Step T2.3: Generate the Image

Use the helper functions from the plugin's `scripts/lib/cover-api.sh`:

**For OpenAI:**
```bash
source "${PLUGIN_DIR}/scripts/lib/cover-api.sh"
openai_generate_image "the full prompt" "manuscript/assets/cover-illustration.png" "1024x1536"
```

**For Flux (BFL):**
```bash
source "${PLUGIN_DIR}/scripts/lib/cover-api.sh"
bfl_generate_image "the full prompt" "manuscript/assets/cover-illustration.png" "1024x1536"
```

If the first result isn't right, offer to generate additional variations with adjusted prompts. Save as `cover-illustration-1.png`, `cover-illustration-2.png`, etc.

### Step T2.4: Author Picks Favorite

Present the file paths. The author opens them to review and picks one.

### Step T2.5: Text Compositing Decision

Ask: "Would you like me to add title and author text as a crisp overlay (recommended — AI text rendering is unreliable), or use this illustration as the complete cover?"

**If overlay → compositing workflow:**

1. Design the text layout considering the illustration's composition — where is there space for text? What colors contrast well?
2. Write a composite SVG that references the raster illustration as the base layer:

```xml
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="1600" height="2400" viewBox="0 0 1600 2400">
  <!-- Base illustration -->
  <image href="cover-illustration.png" width="1600" height="2400"/>
  <!-- Optional readability band -->
  <rect width="1600" height="500" y="0" fill="black" opacity="0.35"/>
  <!-- Title -->
  <text x="800" y="300" text-anchor="middle" font-family="'Playfair Display', serif"
        font-size="120" fill="white" letter-spacing="4">TITLE</text>
  <!-- Author -->
  <text x="800" y="2200" text-anchor="middle" font-family="'Cormorant Garamond', serif"
        font-size="48" fill="white" letter-spacing="8">AUTHOR NAME</text>
</svg>
```

3. Save to `manuscript/assets/cover-composite.svg`.
4. Convert to PNG — this requires `rsvg-convert` specifically (sips cannot handle SVG with embedded raster images):
```bash
if command -v rsvg-convert >/dev/null 2>&1; then
    cd manuscript/assets && rsvg-convert -w 1600 -h 2400 -o cover.png cover-composite.svg
else
    echo "ERROR: Text compositing requires librsvg. Install with: brew install librsvg"
    echo "Cannot produce final cover PNG without it."
    exit 1
fi
```

**Verify the PNG after conversion:**
```bash
if [[ ! -s manuscript/assets/cover.png ]]; then
    echo "ERROR: PNG conversion produced an empty or missing file."
    exit 1
fi
echo "Cover PNG verified: $(wc -c < manuscript/assets/cover.png) bytes"
```

**If as-is → use illustration directly:**

Copy the chosen illustration to `manuscript/assets/cover.png` and update configuration.

### Step T2.6: Update Configuration and Commit

Same as Tier 1 Step T1.6. Commit message: `"Cover: generate AI illustration for {title}"` or `"Cover: generate AI illustration with text compositing for {title}"`.

## Coaching Level Behavior

Read `project.coaching_level` from storyforge.yaml.

### `full` (default)

Claude analyzes the story, proposes a bold cover concept, and executes it. Be opinionated — you know what makes a cover work. Present your concept with conviction, compose the SVG or craft the image prompt, and iterate on author feedback. You are a creative partner, not a service desk.

### `coach`

Help the author discover their own cover vision. Ask guiding questions:

- "What single image or symbol represents your story?"
- "What mood should the cover convey — dark and brooding, bright and hopeful, mysterious, warm?"
- "Look at covers of books similar to yours. What elements do you want to echo? What do you want to avoid?"
- "Where should the reader's eye go first — the title, or the imagery?"
- "What colors feel right for this book?"

When the author has a vision, execute it technically. Save a design brief to `working/coaching/cover-brief.md` before producing the cover.

### `strict`

Claude handles technical execution only. The author provides all creative direction:

- Color palette (specific hex values or descriptions)
- Imagery description (what to depict, composition)
- Layout preferences (title placement, sizing)
- Typography choices (font family, weight, style)

Save a requirements checklist to `working/coaching/cover-checklist.md`. Execute exactly what the author specifies. No proposals, no alternatives, no opinions.

## Commit After Every Deliverable

Every artifact gets its own commit:
- Saved the SVG cover? Commit and push.
- Generated an AI illustration? Commit and push.
- Completed text compositing? Commit and push.
- Updated production configuration? Commit and push.

```
git add -A && git commit -m "Cover: {what was done}" && git push
```

## Coaching Posture

The cover is the first thing a reader sees. It does more to sell a book than any blurb or review. Treat it with the creative seriousness it deserves.

Be direct about what works visually. If a concept isn't strong, say so. If the author's idea is great, build on it with enthusiasm. The goal is a cover that makes someone pick up the book — distinctive, genre-appropriate, and true to the story.

For Tier 1 (SVG), remind the author that these covers are typographic and symbolic — they won't look like a photographic thriller cover or a painted fantasy cover. They are designed to be elegant, distinctive, and professional. Think Penguin Classics, Vintage paperbacks, or indie literary presses — typography and composition can be stunning.

For Tier 2 (AI), set expectations about resolution (epub-quality, not print-at-300-DPI) and the iterative nature of prompt-based generation. The first result is rarely the final one.
