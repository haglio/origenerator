
## Test fixtures must be fabricated, never copied from the real library

Every fixture value that stands in for library data — a video title, a filename,
a performer or studio name, prompt text — must be **invented**. Never paste a
real one out of the media library to make a test feel realistic.

This is not a style note. It is the single thing that has actually leaked private
data into these repos: an agent writing a test reached for a real filename or
performer name because it was handy, and it rode into a public commit. Nothing in
the app's *design* pulls library text into source — the library lives outside
every repo, read at runtime through the git-ignored overlays — so this habit is
the only remaining path for a real name to get committed, and the only thing
stopping it is you following this rule.

Do not lean on the sanitize guard to catch it. `tools/sanitize_guard.py` fails
the suite when a **known** blocked term appears in the tracked tree, but a brand-
new performer name it has never seen passes every check and lands. The guard is a
backstop for names already known; it cannot see the next one.

So fabricate fully. Use `Jane Doe`, `Example Studio`, `scene one`, the
`alpha`/`beta`/`gamma` act placeholders the committed `content.example.json`
already uses. The near miss that still counts: taking a real filename and
changing a character or two — it is still that clip, still that performer. Make
it up from scratch, don't lightly edit a real one.

## A model picker offers only what its graph can run

`ComfyUI/models/<category>` is a folder, not a catalogue. `checkpoints` holds WAN
and LTX video models beside the SDXL ones; `diffusion_models` holds WAN, Flux,
Qwen and bare SDXL UNets together; `loras` holds a LoRA for every one of those,
plus the occasional full checkpoint filed there by mistake. So a dropdown built
from a plain folder listing offers runs that can only error — and worse, presents
them as choices the user is being asked to make. That is exactly how the SDXL
Text-to-Image form came to show WAN 2.2's high/low expert pairs, with nothing to
say which one to pick or that neither belonged.

So every picker states what its graph runs: `list_model_files(category, fallback,
accepts=…)` and `list_lora_files(fallback, accepts=…)`, with `accepts` a family
from `workflows/model_arch.py`, a tuple of them, or `ANY` for a category that
genuinely takes anything (the ESRGAN upscalers). Add `expert="high"` / `"low"` on
a slot that fills one half of WAN 2.2's expert pair. `accepts` is keyword-only
with no default, so a new workflow cannot list a folder without answering the
question — forgetting is a `TypeError`, not a dropdown that quietly went back to
offering everything. Two registry-wide tests in `tests/test_workflows.py` cover
every workflow, present and future, so nothing here needs a name added to a list.

The families are read from each file's own header, never its name — installed
here is a checkpoint whose name says Flux and whose tensors say SDXL, and the
tensors are right. **Unrecognized is not unwanted:**
`describe()` returns `arch=None` for a file it cannot read or match, and every
filter keeps those. Be wrong in that direction. A listed option that errors on
submit costs one run and says why; a working model missing from the dropdown has
no symptom at all, and the user cannot even tell there is something to look for.
The near miss that still counts: tightening a signature so an unfamiliar file
lands in a family rather than in `None` — a confident wrong answer hides the
model, where the honest shrug only leaves it listed.

## Judging a branch before it lands

Every worktree carries `launch_preview_branch.vbs` (tracked). Double-clicking it
runs THAT worktree's code as its own app instance: the primary checkout's venv,
the worktree's own `state/`, and `ORIGENERATOR_BRANCH_SESSION=1` — under which
the app seeds its database from the primary install's and skips the library
maintenance only the live app should do (see `origenerator/branch_session.py`).
Two things to do before handing one over: **re-copy the primary's
`content.local.json` into the worktree root every time**, and tell the user to
close the live app first (two instances contend for ComfyUI). Generations made
in a branch session are not lost to it: the live app's next launch adopts them
out of the worktree's database as first-class rows
(`branch_session.adopt_branch_rows`).

Re-copy, not copy-once. The overlay is where `project_roots` lives, and
`seed_branch_db` finds the primary database through it — so a worktree carrying
a copy taken weeks ago, from before a root moved or a key was added, resolves a
primary that isn't there, **returns False without raising, and logs nothing at
all**. The session then comes up on an empty database with no library: no seed
line in `state/origenerator.log`, a ~36 KB `state/origenerator.db`, and a
gallery showing nothing. That is the signature — if a preview has no content,
diff the two `content.local.json` files before looking anywhere else. Renaming
the branch database aside to force a fresh seed does nothing while the overlay
is stale, because the seed was never the part that failed.

The preview is part of delivering any user-facing change, not an extra: the
user judges mergability by clicking through the real app, and skipping the
handoff leaves him "just guessing at whether it's mergable" (his words, from
the session that forced this flow into existence). **It comes BEFORE the pull
request, and his verdict is what opens one** — see Landing below, where opening
a non-draft PR here merges the work hands-off within about twenty minutes.
A preview handed over alongside an already-open PR is not a review, it is a
courtesy notice: the queue lands the change while he is still clicking (that is
what happened on #33, 2026-08-13). Three delivery lessons from the session that
forced this flow into existence (2026-08-12):

- **NEVER launch the preview yourself. Hand the link and stop.** Running the vbs
  — `cscript`, `wscript`, `Start-Process`, or a bare `python -m origenerator` —
  puts an app window over whatever he is doing and takes his focus: something
  popping up unannounced, which he closes in irritation, and his live app goes
  with it (both instances I launched and his running app were gone inside two
  minutes, 2026-08-15; he asked for this law by name). Launching is HIS act, on
  his schedule. This overrides the older "launch it once yourself to confirm it
  comes up clean" rule, which is what produced the failure. The pre-handoff
  check is windowless instead: `python -m pytest tests/test_launch_smoke.py`
  replays the launch's whole import phase in a fresh interpreter under the
  launcher's own cwd and `PYTHONPATH`, which is precisely what a dead icon fails
  at — and a launcher that breaks past that, he tells you about in one line.
  `~/.claude/hooks/block-visible-origenerator.py` blocks the visible launch
  mechanically, so this one does not rest on prose. Same reason his live app
  must never be closed by you — every Origenerator window is a `python` process
  titled "Origenerator", so a title-matched close shuts his app too
  (2026-08-13). The near miss that still counts: launching it "just for a few
  seconds" to read `state\origenerator_launcher.log` — those seconds are the
  window on his screen, and that is the whole failure.
- Hand a launcher link to the vbs FILE itself — never its folder,
  never a shell command, and never any launcher sharing a filename with the
  live app's. The user was once handed the worktree's `launch_origenerator.vbs`
  by that name; he clicked the identically named launcher he runs daily, and a
  whole "still doesn't work" review cycle ran against the OLD app while the fix
  sat unlaunched. `launch_preview_branch.vbs` is named distinctly exactly so
  that cannot recur.
- When "still doesn't work" survives a fix, check WHICH app his runs actually
  hit before debugging further: generation rows land in the `state/` database
  of whichever checkout served them, and their `workflow_version` names the
  code that ran.

## Verify the physical end, not just the suite

Device or UI work is not delivered because tests pass — three rounds of "it
doesn't work" (2026-08-12) came from exactly that gap. Probes that settle it
from a session, no hardware in view: send
`origenerator.osr2.Osr2Broker.park()` and stat
`../fun_time/state/osr2_serial_tx.txt` (its mtime moves iff UDP → broker →
serial happened; `broker_heartbeat.txt` is broker liveness); grep each state
dir's `origenerator.log` for "OSR2 stroke engaged" / "streaming" to see whether
the app ever actually drove; render a widget offscreen and look at the PNG
(`widget.grab().save(...)` — offscreen has no fonts, so text is tofu there but
fine live); and check which instance the user is running from the launch lines
at the top of each state dir's log — the "main app" can be on pre-merge code.

## Landing — GitHub merge queue, not local ff-merge

This repo is public at `github.com/haglio/origenerator` with a merge-queue ruleset on
`main`, so the global "ff-merge into the primary checkout under
`.git/agent-merge.lock`" flow does NOT apply here:

- **His verdict on the preview opens the PR — nothing else does.** Opening a
  non-draft PR here is not "proposing" the change, it is landing it:
  `.github/workflows/auto-merge.yml` arms auto-merge the moment one opens, and
  the queue merges it hands-off once the gate is green, about twenty minutes
  later. So the order is preview → his word → PR, never PR-and-preview together.
  If you want the branch pushed and visible before he has looked, open it
  `gh pr create --fill --draft` (that workflow exempts drafts on purpose) and
  `gh pr ready` once he says it's good.
- **Land through a pull request.** From your worktree: commit, `git fetch origin
  && git rebase origin/main`, `git push -u origin <branch>`, then
  `gh pr create --fill`. Auto-merge arms itself; the queue rebases your PR onto
  `main`, runs the required check, and merges it when green. Don't ff-merge into
  the primary checkout, don't push `main` directly, and never force-push `main`.
- **The branch is pruned for you when it merges** — this repo has GitHub's
  "automatically delete head branches" on. A branch you abandon without merging
  is still yours to remove: `git push origin --delete <branch>`.
- **The `.git/agent-merge.lock` is retired here** — the GitHub queue serializes.
- **Sync local checkouts by pulling.** `main` advances only on origin (via the
  queue), so the primary checkout and worktrees update with
  `git pull --ff-only origin main`; the running app self-updates the same way.
  The primary is only ever fast-forwarded — never reset or merged-into.
- **A red required check** (`.github/workflows/merge-gate.yml`) can't land.

Everything else in the global CLAUDE.md — work in a worktree, green tests before
you push, clean handoff — still applies.
