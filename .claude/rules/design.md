# Design contract - teknobu-kit

<!-- teknobu-kit v3.2. The design-reviewer agent judges against this file. Replace the facts below with the
product's brand guidelines (docs/BRAND.md if present); keep the shape. -->

## Colour
- Colour comes only from semantic tokens (CSS custom properties -> semantic Tailwind classes). No hex, rgb(), hsl()
  literals or palette utilities (`bg-slate-100`, `text-white`) in components.
- Primary / call to action: Teknobu teal `#00AF9F` (token `--primary`). It is the only call-to-action colour.
- Status colours carry meaning only (success, warning, error, neutral); never decorative.

## Type
- Families: Manrope (UI, 400/500/600), JetBrains Mono (code, metadata).
- Weights: 400 running text, 500-600 headings and actions. Nothing heavier.
- Body 14-16px; eyebrow/meta 11-13px; never below 11px.

## Surface
- Radius: 4px.
- Borders over shadows: 1px hairlines for separation; shadows only for genuinely floating elements.
- Put colour on the value, not behind it.

## Motion
- Only to communicate state; short (<= 300ms), ease-out; no parallax, no bounce.

## Explicitly off-brand
- Default AI aesthetics: Inter/Poppins-by-default, purple-indigo gradients on white, glassmorphism, emoji in UI copy,
  stock futuristic imagery, drop shadows as primary depth.

## Design lint
- none yet; the reviewer reads source
