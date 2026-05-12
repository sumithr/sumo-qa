# sumo-qa branding

Three logo concepts. **Open `preview.html`** to see them side-by-side with proper typography (Anton + JetBrains Mono loaded via Google Fonts), on light and dark backgrounds.

```bash
open docs/branding/preview.html   # macOS
# or just drag preview.html into any browser
```

## The concepts

### 1. `logo-stamp.svg` — Hanko

Solid red Japanese stamp with hard inner border. Stacked `SUMO` / `QA` wordmark in heavy condensed white, mawashi bar between them. References both the traditional `hanko` (personal seal) and a QA approval stamp at the same time.

**Best for:** GitHub avatar · social card · favicon

### 2. `logo-wordmark.svg` — Wordmark

Ultra-condensed black `SUMO` with red `QA` deliberately overlapping the trailing `O`. Red mawashi underline with a hard black knot. Tiny mono baseline tick (`v0.1.2 · apache-2.0`) gives it engineering-ledger character.

**Best for:** README banner · slides · sticker run

### 3. `logo-ring.svg` — Dohyo

Off-centre red dohyo (the sumo ring) with a hard black depth shadow underneath. Brutalist squared `S` geometrically carved into the centre — not handwriting, construction. Compact `SUMO·QA` wordmark below.

**Best for:** Application icon · cover art · merch

## Typography

The wordmark glyphs in each SVG are set in **Anton** (Google Fonts) with a fallback stack of `Impact, Arial Black, sans-serif` for systems without Anton — strong even on the fallback. The `preview.html` loads Anton + JetBrains Mono from Google Fonts to show the intended typographic weight.

## Palette

| | hex | role |
|---|---|---|
| ink black | `#0a0a0a` | primary weight |
| sumo red | `#dc2626` | accent · stamp · belt |
| cream | `#faf5ee` | paper background · wordmark on dark |

## What gets wired when you pick one

When you say which (or "none, generate via AI"), the chosen SVG is copied to `assets/logo.svg` and referenced as:

- Top-of-README banner
- `composerIcon` in `.codex-plugin/plugin.json`
- Favicon (rasterised later)

The other two stay in `docs/branding/` as alternates.
