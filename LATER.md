# LATER

Ideas that are real but not v1. The design doc's scope rule: five organs
(six, post-correction), four milestones — everything else lives here.

## ~~Desktop pet frontend (alternative to the menubar widget)~~ — PROMOTED

**2026-07-10:** No longer deferred. Mannas made the menu-bar tamagotchi-style
pet the M3 end goal, including per-action-confirmed execution of remedies.
See the design doc's "Frontend & Agency Pivot" section — the sleeping-sage
restraint framing below carried over as the pet's core personality.

## (original deferred entry, kept for the reasoning)

**Idea (Mannas, 2026-07-10):** instead of (or alongside) the M3 menubar
widget, Vidura lives on screen as a small pet/companion.

**The tension:** the v1 success criterion is "zero moments of 'this is
Clippy'" — and an animated screen pet is the Clippy form factor. Vidura's
first principle is that silence is the default state.

**The version that works:** a pet whose entire personality is restraint.
It sleeps — genuinely inert — almost always. The rare moment it stirs and
opens its eyes IS the notification. Because it never moves, movement
becomes an event. This is a more embodied version of "a notification
means Vidura is confident" than a menubar badge, and it fits the
counselor framing (Vidura in meditation; speaks only when it matters).

**Practical notes:**
- Still SwiftUI: a borderless, transparent, always-on-top NSWindow
  instead of a menubar popover. Comparable build effort to the widget.
- The frontend is a thin shell over the same core (Approach C), so this
  is swappable/parallel later without touching the reflector, memory, or
  watcher.
- Interaction rules would need care: draggable, click to open the
  suggestion card, never steals focus, hidden in screen-sharing mode.

**Decision:** M3 ships the menubar widget per the plan. Revisit this as
an M4+ alternative frontend once the suggestion quality has earned an
ambient presence.
