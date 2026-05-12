# sumo-qa branding

Three logo concepts for sumo-qa. Open each `.svg` in your browser or any image viewer to compare. Pick one (or none) and I'll wire it into the main README + plugin manifest.

## Concepts

### 1. `logo-line.svg` — Minimalist line art

Single-stroke wrestler silhouette in shiko stance (the classic wide stance, knees over toes). Monochrome, transparent background, scales cleanly down to favicon size. Best for documentation headers; lowest brand presence.

### 2. `logo-geometric.svg` — Geometric on a dohyo

Abstract sumo (head + body stacked) inside a circular dohyo (the sand-coloured ring). Red mawashi belt across the middle as the colour accent. Reads at small sizes and from a distance. Best for repo social-card / GitHub avatar.

### 3. `logo-bold.svg` — Bold mark with Q

Filled silhouette with a red mawashi carrying a serif "Q" — the QA tie-in is visible at a glance, so it earns its keep as a mark you might put on slides / a sticker. Strongest brand presence; least subtle.

## How to view locally

```bash
# macOS — open all three in default viewer
open docs/branding/*.svg

# any platform — open in your browser
python3 -m http.server 8000
# then visit http://localhost:8000/docs/branding/
```

## What gets touched when you pick one

When you say which one (or "none, I'll generate via Midjourney later"), I'll:

- Copy the chosen SVG to `assets/logo.svg`
- Embed it at the top of `README.md` (replacing the H1 heading)
- Reference it as `composerIcon` in `.codex-plugin/plugin.json`
- Leave the other two concepts in `docs/branding/` as alternates

If you want to upgrade later to an AI-generated raster (Midjourney / DALL-E / Stable Diffusion), drop the file into `assets/` and point the README / Codex plugin at it.
