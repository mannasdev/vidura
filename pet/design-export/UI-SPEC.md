# Vidura Menu-Bar Pet — UI Spec

Source: Pencil document `616fb6b5-a712-4cbc-af00-a3b9e6d04246/pencil-new.pen`
Trees read: `YOU4V` "Vidura · Menu Bar Dropdown" (light child `i5lGr` → `k1Rvlc` Popover Light; dark child `pwUqz` → `neHVE` Popover Dark), `gnUzM` "Vidura · Character — Six Expressions".
Reference images: `panel-light.png`, `panel-dark.png`, `expressions-sheet.png`, plus exported character assets `cat-*.png` (384×384px = 96×96pt @4x).

All values below are exact node properties pulled from the .pen file (not estimated from screenshots) unless marked "Reading:".

---

## 1. Design Tokens

### 1.1 Colors (variable name → light / dark hex)

| Token | Light | Dark | Used for |
|---|---|---|---|
| `bg-panel` | `#F7F4EE` | `#201D18` | Popover root background |
| `bg-card` | `#FFFFFF` | `#2A2620` | Suggestion card background |
| `bg-evidence` | `#F3EFE6` | `#191612` | Evidence/quote block background |
| `bg-subtle` | `#EFEAE0` | `#343028` | (reserved — hover/pressed states, not directly used in this mock) |
| `border` | `#E4DDCE` | `#3A342B` | Popover stroke, card stroke, footer rule |
| `ink` | `#3B2C1A` | `#3B2C1A` | Not theme-bound; used in character pixel art (outline color) |
| `text-primary` | `#2B2419` | `#EDE6D9` | Name, summary body text |
| `text-secondary` | `#6E6353` | `#A79B87` | Hero subtitle, meta text, dismiss label, quote text |
| `text-tertiary` | `#9A8F7C` | `#6E6355` | Footer text, footer links, scene labels |
| `accent` | `#B45309` | `#E5A158` | Mood label, "Do" button label & tag text |
| `accent-subtle` | `#B453091A` (10% alpha) | `#E5A15821` (13% alpha) | "Do" button fill, tag chip fill |
| `danger` | `#A23B2A` | `#D08273` | Reserved (not used in this mock's visible state; likely for destructive confidence/errors) |
| `proud` | `#55702C` | `#A9BE7B` | Reserved for "Proud" mood accent (not shown in these two mock states) |
| `proud-subtle` | `#55702C14` | `#A9BE7B1A` | Reserved, pairs with `proud` |
| `face` | `#E9A23B` | (not themed) | Character fur base color |
| `face-deep` | `#C97F25` | (not themed) | Character fur shading color |

Non-variable literal colors seen directly on nodes (theme-specific, not tokenized in the variable table — treat as fixed per-theme constants):
- Accept button: fill `#2B2419` (light) / dark-panel equivalent not shown separately — dark mock has no suggestion card to compare, but the light Accept fill is a near-black ink tone (matches `text-primary` light value), label `#FFFFFF`.
- Menu bar bg (mock only, not app UI): light `#F4F1E9`, dark `#26221B`.
- Popover shadow: light `#2B241740` (25% black-brown) blur 50, offset (0,18); dark `#00000073` (45% black) blur 50, offset (0,18).
- Quote bar accent: `#B4530980` (50% alpha of accent-light) — used in both quote-bullet bars in the light mock; no dark suggestion-card equivalent captured (dark mock shows empty state instead).

### 1.2 Typography

Font families (from variables): `font-serif` = **Lora**, `font-ui` = **Inter**, `font-mono` = **IBM Plex Mono**.

| Role | Family | Size | Weight | Letter spacing | Line height | Color token |
|---|---|---|---|---|---|---|
| Pet name ("Vidura") | Lora | 22 | 600 (semibold) | — | — | text-primary |
| Mood label ("STIRRING"/"ASLEEP") | Inter | 11 | 600 | 1.5 | — | accent (light: `#B45309`) / text-tertiary-ish (dark "ASLEEP" uses `#6E6355`, i.e. dark text-tertiary — see §7 ambiguity) |
| Hero subtitle ("One thing to say." / "Nothing to say.") | Inter | 13 | normal (400) | — | — | text-secondary |
| Tag chip text ("repeated-error-loop") | IBM Plex Mono | 10.5 | normal | — | — | accent |
| Card meta right ("72% · seen 3×") | Inter | 11 | normal | — | — | text-tertiary |
| Suggestion summary body | Inter | 14.5 | 500 (medium) | — | 1.5 | text-primary |
| Evidence/quote line | IBM Plex Mono | 11 | normal | — | — | text-secondary |
| Button — Dismiss | Inter | 12.5 | 500 | — | — | text-secondary |
| Button — "Do — …" | Inter | 12.5 | 600 | — | — | accent |
| Button — Accept | Inter | 12.5 | 600 | — | — | white (`#FFFFFF`) |
| Footer left ("Last counsel · …") | Inter | 11 | normal | — | — | text-tertiary |
| Footer links (Pets/Settings/Quit) | Inter | 11 | normal | — | — | text-tertiary |
| Empty state primary ("Nothing earned.") | **Lora** | 17 | normal (400) | — | — | text-primary |
| Empty state secondary ("Silence is correct.") | Inter | 13 | normal | — | — | text-secondary |
| Scene reference labels (mock-only "LIGHT · COUNSEL WAITING") | Inter | 12 | 600 | 1 | — | text-tertiary — **not part of app UI**, this is Pencil-canvas scene annotation |

### 1.3 Spacing, Radii, Borders, Shadow

- Popover corner radius: **14px**
- Popover border: **1px**, `border` token color
- Popover shadow: `blur 50, offset (0, 18)`, color `#2B241740` light / `#00000073` dark (outer shadow)
- Suggestion card corner radius: **10px**, border **1px** `border` token, background `bg-card`
- Evidence block corner radius: **8px**, background `bg-evidence`, padding **10 (v) / 12 (h)**, internal gap **7px** between quote lines
- Tag chip corner radius: **4px**, padding **3 (v) / 8 (h)**
- Button corner radius: **7px** (all three buttons)
- Quote bullet bar: 3px wide × 14px tall rounded rect (`cornerRadius: 2`), color `#B4530980`, gap 9px to text
- Menu-bar mark badge (mock menu bar icon) corner radius: **5px**

---

## 2. Panel Structure (top → bottom)

Popover frame (`Popover Light` / `Popover Dark`): width **400pt**, `layout: vertical`, no explicit fixed height (hugs content — confirms prior commit "panel hugs its content"), `clip: true`, corner radius 14, border 1px, background `bg-panel`.

Top-to-bottom children, in order:

1. **Hero** — frame, `width: fill_container`, horizontal layout (`alignItems: center`), padding **[18 top, 20 right, 14 bottom, 20 left]**, gap **18px** between face and text column.
2. **Suggestions** (light only; replaced by **Empty State** in dark/empty case) — vertical frame, padding **[0 top, 16 right, 16 bottom, 16 left]**, gap 12px. Contains one or more **Suggestion Card** frames (gap 12px between multiple cards, per container gap).
3. **Footer Rule** — 1px full-width horizontal divider, color `border` token.
4. **Footer** — horizontal frame, `justifyContent: space_between`, `alignItems: center`, padding **[10 top/bottom, 20 left/right]**.

No fixed fill between Hero and Suggestions/Empty-state — they sit directly adjacent (Hero's own bottom padding of 14 is the only gap).

### 2.1 Hero (header)

- Character image ("Hero Face"): a `ref` to the mood's `Face / <Mood>` component, rendered at the component's **native size, 96×96pt** (no scale/size override on the ref node). Source pixel-art frame is authored on a 24×24 "pixel" grid at 4pt/pixel = 96×96pt; exported bitmap assets are 384×384px (@4x), matching 96pt @4x exactly.
- Text column ("Hero Text"): vertical stack, gap **4px**, containing:
  1. Name — "Vidura", Lora 22/600, text-primary
  2. Mood — uppercase status word (e.g. "STIRRING", "ASLEEP"), Inter 11/600, letter-spacing 1.5
  3. Subtitle — one line of prose, Inter 13/400, text-secondary
- No status dot/badge on the hero itself in this mock. (The only "dot" badge in the whole design is the small accent-colored ellipse on the **menu-bar mark glyph** — see §5 — signaling "has something to say" at the OS menu-bar-icon level, not inside the panel.)

### 2.2 Suggestion Card

Single card observed (light mock), `Suggestion Card` frame: vertical layout, padding **16** (all sides), gap **12px** between its 4 stacked sections, corner radius 10, border 1px `border`, background `bg-card`.

Sections top→bottom:

1. **Card Meta** row (`justifyContent: space_between`, `alignItems: center`, width fill):
   - Left: **Tag chip** — pill-ish frame, corner radius 4, padding 3/8, fill `accent-subtle`, containing mono text (IBM Plex Mono 10.5, `accent` color) — the suggestion's category slug, e.g. `repeated-error-loop`.
   - Right: **Meta text** — "72% · seen 3×" pattern (confidence % + occurrence count), Inter 11/400, text-tertiary. This is a single concatenated string, not two separate elements — format is `"{confidence}% · seen {n}×"`.
2. **Summary** — the main suggestion prose, Inter 14.5/500, text-primary, line-height 1.5, full width, wraps to multiple lines.
3. **Evidence** block — vertical frame, padding 10/12, gap 7, corner radius 8, background `bg-evidence`. Contains **N "Quote" rows** (2 shown), each: horizontal, `alignItems: center`, gap 9 — a 3×14 rounded accent-bar (color `#B4530980`) followed by one line of IBM Plex Mono 11/400 text-secondary, truncated with a trailing `…`. This reads as a terminal/log excerpt treatment (monospace, muted, left-rule bar per line — like a blockquote/diff-style marker).
4. **Card Actions** row — horizontal, `alignItems: center`, gap 8, full width:
   - **Dismiss** — plain text button, no fill/border, padding 7/10, corner radius 7 (radius present but invisible since no fill), label Inter 12.5/500, text-secondary. Lowest visual weight — looks like a plain label, not a button.
   - **Spacer** — `fill_container` width, height 1, pushes Dismiss left and the two remaining buttons right.
   - **"Do — {action}"** — secondary/tinted button, fill `accent-subtle`, padding 7/12, corner radius 7, label Inter 12.5/600, color `accent`. Middle visual weight — a tinted pill, reads as the "smart suggested one-click fix" affordance (label is dynamic: `"Do — " + shortActionLabel`, e.g. "Do — Install gh CLI").
   - **Accept** — primary/solid button, fill `#2B2419` (ink/near-black, light mode), padding 7/14, corner radius 7, label Inter 12.5/600, color `#FFFFFF`. **Highest visual weight** — solid dark fill, white text, most padding (14 vs 10/12 for the others). This is the primary CTA.

   **Visual hierarchy ranking: Accept (solid dark, primary) > Do (tinted accent, secondary) > Dismiss (plain text, tertiary).**

### 2.3 Footer

- Full-width 1px rule above (`border` token color) then padding 10 (v) / 20 (h), horizontal, `justifyContent: space_between`, `alignItems: center`.
- Left: **"Last counsel · 6 days ago"** — single string, format `"Last counsel · {relative time}"`, Inter 11/400, text-tertiary.
- Right: **Footer Links** — horizontal group, gap 14, three text items "Pets", "Settings", "Quit", each Inter 11/400, text-tertiary. Reading: plain text links/menu triggers, no buttons/dividers between them beyond the 14px gap.

### 2.4 Empty State (dark mock)

Replaces the Suggestions block entirely when there is nothing to review. Frame: vertical, `alignItems: center`, gap **7px**, padding **[34 top, 20 right, 44 bottom, 20 left]**.

- Primary line — **"Nothing earned."** — **Lora 17/normal** (this is the one other place serif appears besides the pet's name — gives the empty state a quiet, editorial tone rather than a system-message tone), text-primary.
- Secondary line — **"Silence is correct."** — Inter 13/400, text-secondary.
- Both center-aligned, no icon/illustration — text-only empty state.
- Asymmetric vertical padding (34 top / 44 bottom) gives it a slightly bottom-heavy centered feel within the available space rather than being perfectly centered.

---

## 3. Cross-theme structural diff

Light and dark popovers share identical structure/spacing; only colors swap via the token table in §1.1, plus:
- The **light mock shows the "has a suggestion" state** (Hero mood STIRRING + Suggestion Card).
- The **dark mock shows the "nothing to review" state** (Hero mood ASLEEP + Empty State).

These are two different application *states*, not a light/dark content difference — implementers should support both states in both themes (i.e., Empty State must also be styleable in light mode, and Suggestion Card must also render correctly in dark mode, even though the Pencil mock only shows one state per theme). Use the dark-mode token column already defined in §1.1 for the card/evidence/button colors in the "suggestion in dark mode" case, since no such node exists to read directly — see §7 ambiguity.

---

## 4. Menu Bar Mark (mock chrome, for context — not app-rendered by Vidura itself except the icon)

The mock's fake menu bar (560×26pt, not part of the actual popover, just presentation context) shows a **Vidura status-bar icon**: a 26×22pt rounded-rect (corner radius 5) button containing an 18×18 "Mark Glyph" — a small pixel-style rounded head shape with two rectangular eyes, matching the cat's silhouette in miniature (ears/"bun" nub, rounded head, two eye slits) rendered in ink color, sitting on a faint background:
  - Light mode icon: glyph color `#2A251D` (near-black) on `#00000012` (7% black) rounded-rect background, **plus a small accent-colored badge dot** (5×5 ellipse, `#B45309`) at the top-right corner of the glyph — this is the "has something to say" indicator at the OS menu-bar level.
  - Dark mode icon: glyph color `#EDE8DE` (near-white) on `#FFFFFF1E` (12% white) rounded background — **no badge dot shown** (matches the dark mock's empty/asleep state — nothing to flag).
  - Reading: the badge dot only appears when Vidura has counsel waiting, mirroring the "STIRRING" vs "ASLEEP" hero states. This is the menu-bar equivalent of the in-panel hero mood.

---

## 5. Character Asset Mapping

Six mood frames in `gnUzM` tree, each a reusable 96×96 pixel-art frame on a 24×24-unit (4pt/unit) grid, exported as 384×384px PNGs (@4x):

| Pencil frame name | Exported asset | Mood/status label | Used in mock as |
|---|---|---|---|
| `Face / Asleep` | `cat-asleep.png` | ASLEEP | Dark mock hero (empty state) |
| `Face / Content` | `cat-content.png` | CONTENT | (not shown in either mock; sheet only) |
| `Face / Stirring` | `cat-stirring.png` | STIRRING | Light mock hero (has-suggestion state) |
| `Face / Proud` | `cat-proud.png` | PROUD | (not shown in either mock; sheet only) |
| `Face / Concerned` | `cat-concerned.png` | CONCERNED | (not shown in either mock; sheet only) |
| `Face / Recognition` | `cat-recognition.png` | RECOGNITION | (not shown in either mock; sheet only) |

All six sit in one reference sheet frame (`gnUzM`, "Vidura · Character — Six Expressions", not part of the shipped panel) at 44px gaps, each face 96×96 with a caption label below (Inter 13/400, text-secondary) — this sheet is a component-catalog artifact, not a UI screen.

**Rendered size in the panel header: 96×96pt** (native, unscaled `ref`). No separate "small" cropped variant is defined — the same full-face asset is used at header scale in both mock states.

Recommended SwiftUI mapping: an enum `PetMood { case asleep, content, stirring, proud, concerned, recognition }` → asset name `"cat-\(rawValue)"`, rendered in a fixed 96×96 frame in the Hero row.

---

## 6. Deliverable Checklist Recap (quick reference)

- Panel width: **400pt**, height: **hug/intrinsic** (no fixed height token)
- Corner radius: **14** (panel), **10** (card), **8** (evidence), **7** (buttons), **4** (tag), **5** (mark badge)
- Fonts: **Lora** (name + empty-state headline — serif/editorial accents), **Inter** (all UI text), **IBM Plex Mono** (tag + evidence/log text)
- Primary accent: `#B45309` light / `#E5A158` dark
- Button hierarchy: Accept (solid ink) > Do (tinted accent) > Dismiss (plain text)

---

## 7. Ambiguities / Lower-confidence readings

1. **Dark-mode mood-label color for "ASLEEP".** In the dark mock, "ASLEEP" is rendered `#6E6355`, which is exactly the `text-tertiary` (dark) value, not the `accent` (dark) value `#E5A158`. In the light mock, "STIRRING" uses `accent` (light) `#B45309`. This could mean: (a) the mood label always uses the `accent` token except the design happened to pick a muted color specifically for the neutral/asleep state (a deliberate "nothing urgent, muted label" treatment), or (b) it's an authoring inconsistency and should always be `accent`. **My reading: intentional** — "asleep" is the calm/neutral baseline mood and likely should render muted/tertiary rather than in the alert-orange accent, while active/urgent moods (stirring, concerned, recognition, proud) use `accent`. Recommend making mood-label color a per-mood property (`asleep`/`content` → text-tertiary, others → accent) rather than hard-coding accent everywhere — but flagging since only 2 of 6 moods are directly observed in the mock.
2. **Suggestion Card in dark mode / Empty State in light mode.** Neither exists as an actual node in the .pen file — each mock only shows one of the two app states. Token mapping in §1.1/§3 is applied by inference (swap theme tokens, keep structure identical). Low risk since all card/evidence/button colors are theme-variable tokens already resolved for both themes, but there is no dark-mode "Do"/"Accept"/"Dismiss" button screenshot to visually confirm contrast — particularly the **Accept button's dark-mode fill** is not directly specified anywhere (light mock hardcodes `#2B2419`, which is not itself a listed variable, though it equals the `text-primary` light value). Recommend dark-mode Accept fill = `text-primary` dark value `#EDE6D9` with dark ink-colored label for contrast (inverted, same pattern as light), but this is a recommendation, not a read value.
3. **Header face rendered size (96×96pt).** Confirmed via cross-check against the exported `cat-*.png` assets (384×384px = 96pt @4x) and the Pencil `ref` node carrying no size override — high confidence. (An initial pixel-measurement pass against the screenshot suggested something closer to ~64–70pt, but that measurement is unreliable against a scaled/compressed screenshot; the source-of-truth node data and asset dimensions agree at 96×96, so I'm treating screenshot measurement as the imprecise signal here.)
4. **"Do — …" button label truncation/format.** Only one example is shown: `"Do — Install gh CLI"`. Assumed format is `"Do — " + <imperative action label>`, sized to hug content (not fill width) — the row uses a flexible spacer before it, so both "Do" and "Accept" are trailing right-aligned as a pair while "Dismiss" stays pinned left. No evidence of a max-width/truncation rule for long action labels; recommend defining one (e.g. `lineLimit(1)` + `.truncationMode(.tail)`) defensively since real action strings may run longer than "Install gh CLI".
5. **Multiple suggestion cards.** The `Suggestions` container has `gap: 12` implying it's designed to hold more than one `Suggestion Card`, but the mock only shows one card. Assume cards stack vertically with 12pt gaps and identical styling; no evidence of a max-card-count or "show more" affordance.
6. **Confidence display format.** `"72% · seen 3×"` — read as `confidence_percent + "% · seen " + view_count + "×"`. Not fully certain whether "seen 3×" means "this exact suggestion pattern has occurred 3 times" vs "shown to user 3 times" — this is a product/copy semantics question outside the visual spec, flagging for product/eng to confirm string source.
