# Knowledge base — how to use

This folder is the development knowledge base for the repo, written for Claude-based
development (and for humans). First built 2026-09-22 from `board_v3` at commit `6681ffd`;
rewritten the same day for the `boardcam/` implementation of `DESIGN.md`.

Conventions:

- **English prose, Russian terms verbatim.** Code comments, UI, reports and job sheets are in
  Russian; identifiers, report strings and domain words are quoted exactly so you can grep.
  Glossary in `domain.md`.
- **Facts, not aspirations.** Where `DESIGN.md` and the code disagree, the code wins and the
  difference is listed in `DESIGN.md §13` and `status.md`.
- **Line numbers are not given.** Use symbol names and grep.

Reading order for a first session:

1. `../CLAUDE.md` — rules, commands, definition of done.
2. `domain.md` — what is being made and on what machine.
3. `architecture.md` — package layers and the data flow of a run.
4. `gotchas.md` — before touching anything.
5. Then the page matching your task: `geometry.md`, `gcode-safety.md`, `parameters.md`.
6. `status.md` — what is done, what is open, decisions that must not be reopened.
7. `../DESIGN.md` (design and its §13 implementation notes), `../IMPLEMENTATION.md` (how it
   was built, measurements, findings).
8. `landscape.md`, `options.md` — the market and the architecture options behind `DESIGN.md`.

The previous generator's own documents remain in `../board_v3/` (README, PLAN, HANDOFF,
tasks) as the record of the author's intent and shop procedure.

Keep this knowledge base current: when you change behaviour, update the matching page in the
same change. When you learn something the hard way, add it to `gotchas.md`.
