# Veriq UI patterns

### Browser upload workspace

Files: `src/veriq/web/upload.html`, `src/veriq/web/upload.css`  
Last updated: 2026-10-18  
Visual reference: `context/reference/reference.png`

| Property | Token / pattern |
| --- | --- |
| Background | White `--canvas`; blue `--blue: #a9d3fc` to cream `--cream: #fff5df` hero gradient |
| Workspace | Pale `--surface: #f5f8fb`; 1px `#68716b` border; 20px radius |
| Cards | White, 8px radius; no shadow |
| Text — primary | `--ink: #11130f`; Arial / Helvetica |
| Text — secondary | `--muted: #53574f`; Georgia for descriptive paragraphs |
| Hero | Centered Georgia first line; Arial second line; 42–72px, tight tracking |
| Headings | 600 weight; 21px section/card; 30–42px results heading |
| Spacing | 34px workspace padding; 22px card padding; 14px card gap; 96px before results |
| Buttons | Black rectangular buttons, white text; 46px minimum height |
| Hover | `--accent-hover: #33382c` |
| Focus | 3px `#1654b8` outline with 4px offset |
| Accent | `--yellow: #f5ff37` file labels and footer |
| Footer | Oversized olive wordmark with decorative CSS line texture |
| Error | `--error: #9d2721` plus explicit text |

Adapt the reference's editorial typography, generous whitespace, framed workspace and yellow footer to the functional upload flow. Keep native file controls, visible labels, live status messages, and reduced-motion support. Use a single column on narrow screens. No external fonts, scripts, or image dependencies are loaded.

### Favicon

File: `src/veriq/web/favicon.png`
Last updated: 2026-10-18

64×64 PNG, generated with the built-in imagegen tool and resized for browser use. A heavy black V on the frontend's acid-yellow background; no border or additional symbols. Served from `/upload/assets/favicon.png`, included in Python and Appwrite packages. The page's image policy permits same-origin assets.

Generation prompt: Use case: logo-brand. Asset type: production website favicon for Veriq, a workflow verification app. Create ONE flat square favicon image, not a presentation or mockup. Exact text: "V" only. A very bold black (#11130f) sans-serif uppercase V, centered on a solid bright acid-yellow (#f5ff37) square background reaching all image edges. The V should occupy about 72 percent of the width and height with clear balanced margins and feel like a crisp heavy editorial wordmark. Frontend art direction: minimalist Swiss editorial typography, black rectangular buttons, sky blue-to-cream hero, yellow oversized brand footer. Match that confident typography and yellow/black palette. Make the icon instantly legible at 16x16 and 32x32 pixels. Straight clean edges, uniform flat colors, optically centered. No gradients, shadows, bevels, textures, outlines, extra letters, labels, frames, external padding, border, photographic objects, watermark, or additional symbols. Export as a square PNG favicon asset.
