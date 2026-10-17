# Veriq — Design Brief

**Status:** Confirmed visual direction for a future website and report presentation; no UI has been implemented.  
**Product source:** [veriq-plan.md](veriq-plan.md).  
**Visual source:** [reference/reference.png](reference/reference.png).  
**Confirmed direction, 2026-10-16:** Preserve the reference's palette and editorial style while replacing its sustainability content with Veriq's workflow verification story. The initial product remains CLI-first.

## Purpose and audience

Make Veriq feel clear, careful, and inspectable. An n8n developer or automation agency should understand what changes Veriq checks, what the evidence looks like, and where static verification ends. A reviewer should be able to distinguish an approved business rule, a proven violation, and a case that still needs human review.

The website's primary job is to explain the product and lead readers to an example report and CLI documentation. A future dashboard is outside this brief's initial delivery scope. Report styling should support the same visual hierarchy without adding a browser application or graphical report format to P0.

## Reference reading

The provided reference is an Aetherfield sustainability landing page. Its visual vocabulary is a light blue-to-cream hero, a centered two-part editorial headline, small black rectangular calls to action, an overlapping framed product preview, broad whitespace, alternating text/image sections, pale textured bands, blue-treated imagery, thin dividers, and an oversized wordmark on a vivid yellow footer.

The exact original fonts, spacing, and color values cannot be established from the screenshot alone. The values below are proposed Veriq tokens that approximate its visual character, not measured source specifications.

| Observed reference element | Veriq adaptation |
|---|---|
| Sustainability statement in the hero | The business-rule regression promise |
| Impact dashboard preview | A clearly labeled synthetic workflow-diff and evidence report |
| Track / Model / Report / Act feature rows | Import / Define / Compare / Review |
| “Built for clarity” principle band | Reproducible checks, reviewed rules, explicit uncertainty |
| Customer case study | A synthetic procurement walkthrough until a real, authorized case exists |
| Journal section | Real technical guides only when published |
| Large portrait/testimonial | Omit until there is an authorized, attributable testimonial |
| Yellow brand footer | Oversized Veriq wordmark with useful documentation/navigation links |

Use the reference's compositional rhythm rather than copying its logo, environmental metrics, portraits, customer claims, or article content.

## Visual direction

Light, spacious, editorial, and evidence-led. Use large type and a calm gradient for the story; use restrained surfaces and precise alignment for the technical proof. Black buttons provide strong actions. Yellow is a small brand highlight and footer treatment, while blue provides atmosphere and selective emphasis.

Avoid ornamental interface effects that compete with evidence. Thin borders and shallow layering should carry the layout; dense dashboard tiles, heavy shadows, glass effects, neon glows, and dramatic motion would conflict with the chosen reference.

### Proposed color tokens

| Token | Value | Intended use |
|---|---|---|
| `canvas` | `#FFFFFF` | Main page and report background |
| `surface` | `#F5F8FC` | Quiet inset panels and preview background |
| `hero-sky` | `#ADD4FA` | Top of hero gradient and blue image backgrounds |
| `hero-cream` | `#FAF3DE` | Bottom of hero gradient and principle band |
| `brand-yellow` | `#FFEF45` | Footer, occasional highlights, dark text pairing |
| `ink` | `#141414` | Primary text and black action surfaces |
| `muted-ink` | `#555B62` | Supporting text on light surfaces |
| `border` | `#D9DFE5` | Dividers and panel edges |
| `link-blue` | `#2563EB` | Text links and selected evidence references |

Hero treatment: sky at the top fading into cream below, followed by a white body. Keep body text on stable light surfaces. Brand yellow does not itself mean warning or failure.

| Result | Text | Background | Required label |
|---|---|---|---|
| PASS | `#215B32` | `#E7F2E8` | PASS with model scope |
| FAIL | `#9C2B24` | `#FBEAE8` | FAIL with rule and evidence |
| NEEDS_REVIEW | `#654800` | `#FFF3CC` | NEEDS_REVIEW with reason |
| UNSUPPORTED | `#3C475D` | `#EBEEF5` | UNSUPPORTED with capability boundary |
| NOT_APPLICABLE | `#54595F` | `#F0F1F2` | NOT_APPLICABLE with scope explanation |

Use explicit text and distinguishable symbols in addition to color. Failure can coexist with incomplete-coverage warnings; neither should visually hide the other.

### Typography

The reference mixes editorial serif display type with direct sans-serif messaging. Use a system-font first specification until a font family is deliberately selected:

- Serif display: `Georgia, "Times New Roman", serif` for the first phrase of major story headlines.
- Sans-serif: `Arial, Helvetica, sans-serif` for the second phrase, wordmark, navigation, body, and interface labels.
- Monospace: `ui-monospace, SFMono-Regular, Consolas, monospace` for commands, node IDs, hashes, and parameter paths.

Desktop hero type should be approximately 64–84 px; mobile 36–44 px, scaled to preserve meaningful line breaks. Section headings are 32–48 px desktop and 28–34 px mobile. Body copy is 16–18 px with about 1.5–1.65 line height. Evidence tables may use compact text but must remain readable and zoomable. Use heading line height around 1.05–1.15 and avoid orphaned final words.

These are implementation targets, not extracted font measurements. No external font download or new font dependency is required by this brief.

### Layout and surfaces

- Maximum story width: approximately 1,200 px, with narrower text measures around 60–70 characters.
- Desktop grid: 12 columns, generally arranged as balanced two-column sections or a centered narrative. Use 24–32 px gaps.
- Horizontal page padding: 24–48 px desktop, 16–24 px mobile. Section spacing: 80–112 px desktop, 48–64 px mobile.
- Base spacing scale: 4, 8, 12, 16, 24, 32, 48, 64, 80, 112 px.
- Product previews: 1 px outline, approximately 10–16 px radius, minimal shadow. Buttons: black fill, white text, restrained 0–4 px radius, comfortable interactive height.
- Alternate large open areas with compact evidence details. Keep report rows left-aligned and aligned to stable columns.

## Proposed website sequence

### 1. Navigation

Veriq wordmark at left; Product, How it works, Evidence, and Docs at right. The primary action is “View example report.” These are proposed destinations; links become active only when real pages/anchors exist. On small screens, use a keyboard-accessible menu and retain one clear primary action.

### 2. Hero and report preview

Use a centered two-part headline on the blue-to-cream gradient:

> Detect broken business rules  
> before your automations go live.

Supporting copy: “Compare n8n workflow versions against approved rules. Review reproducible findings with exact paths, source references, and clear limits.”

Primary CTA: **View example report**. Secondary CTA: **Read the CLI quickstart**. The first leads to a synthetic audit; the second leads to real installation and usage documentation when available. Do not imply a working download or hosted service before it exists.

Overlap the hero/body boundary with a framed report preview. Use the plan's labeled synthetic procurement example: three rules evaluated, one introduced deterministic failure, and one needs-review item. Show `REQ-004`, baseline PASS → candidate FAIL, and the bypass path. Include a visible “Synthetic example” label and “Static configuration evidence; no runtime verification.”

The preview replaces the reference's environmental chart. Its numbers are scenario data, not measured customer outcomes or product benchmarks.

### 3. Four-step explanation

Pair a workflow/evidence illustration with four rows separated by thin rules:

1. **Import** — Read an exported n8n workflow without running it.
2. **Define** — Commit reviewed business rules with explicit control mappings.
3. **Compare** — Evaluate baseline and candidate under the same policy.
4. **Review** — Inspect supported failures and unresolved coverage before deployment.

Use actual node/path concepts in illustrations. A labeled node alone must not visually imply that live approval was proven.

### 4. Principle band

Use a quiet cream background, optionally with a low-contrast abstract paper texture. Three simple cards communicate:

- **Reproducible checks:** same approved inputs and engine yield stable canonical findings.
- **Human-approved rules:** proposed SOP interpretations remain drafts until reviewed.
- **Visible limits:** unsupported or incomplete evidence stays explicit.

Texture is decorative and should not impair contrast or carry meaning. It is optional; a flat cream background is sufficient.

### 5. Evidence walkthrough

Show the synthetic procurement case as a readable split section: workflow change at left, rule/source/path evidence at right. Let readers follow one concrete counterexample. Avoid decorative business charts or a single green overall score.

### 6. Guides, when real content exists

Use the reference's compact editorial rows for actual guides such as interpreting static findings or authoring a policy. Omit this section until the articles exist. Genuine pilot evidence may later replace a synthetic walkthrough with consent and clear attribution.

### 7. Closing action and footer

Repeat the report/quickstart action on a quiet surface. Finish with a yellow footer and an oversized Veriq wordmark, followed by useful links and the static-analysis boundary. Keep the wordmark readable at narrow widths without forcing horizontal page overflow.

## Report and CLI presentation

P0 reports remain JSON and Markdown. Apply the same information hierarchy through headings, tables, short summaries, and code blocks; do not require custom CSS, a chart library, HTML/PDF generation, or browser rendering.

Display order is gate outcome and model boundary → counts → introduced/changed findings → exact evidence → unresolved coverage → suggested actions. Keep severity, verdict, and comparison classification separate. A green CI exit does not mean every rule passed or every path was understood.

The CLI should use short plain-language summaries and readable IDs. Optional color must preserve meaning in plain text and redirected output. Long paths/hashes can wrap or be copied without changing their underlying value.

## Responsive and accessibility targets

- Design and verify at approximately 375, 768, 1,024, and 1,440 px widths, including zoom and long evidence identifiers.
- Stack split sections on mobile. Keep meaningful text before decorative imagery in reading order. Wide evidence tables may scroll within a labeled region rather than forcing page overflow.
- Provide semantic heading order, descriptive links, visible keyboard focus, labeled controls, and practical touch targets of at least 44 × 44 px.
- Target text contrast of at least 4.5:1 for normal text and 3:1 for large text; check controls, boundaries, and focus treatment against their actual surrounding colors during implementation.
- Use icons plus labels for outcomes; do not rely on color or hover alone. Decorative images receive empty alternative text; meaningful workflow visuals need equivalent textual paths.
- Keep transitions subtle, around 150–250 ms, and honor reduced-motion preferences. Motion is optional and does not reveal essential content.

## Content and acceptance checks

Use precise, restrained language: “supported static check,” “approved rule,” “counterexample,” and “needs review.” Preserve the working brand Veriq. Avoid certification promises, universal safety claims, fabricated testimonials, invented adoption numbers, and unmeasured performance claims.

The design direction is met when the website retains the reference's gradient, mixed editorial type, black actions, whitespace, framed preview, and yellow brand footer while telling Veriq's actual story. A developer should be able to identify the product promise, delivery interface, example evidence, and limits within the opening sections.

During UI implementation, verify mobile reflow, keyboard navigation, contrast on actual surfaces, reduced motion, link destinations, and report-content accuracy. This documentation task does not claim that those UI checks have already passed.
