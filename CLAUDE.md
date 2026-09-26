
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

Do not lean on the sanitize guard to catch it. `app_support.sanitize` fails
the suite when a **known** blocked term appears in the tracked tree, but a brand-
new performer name it has never seen passes every check and lands. The guard is a
backstop for names already known; it cannot see the next one.

So fabricate fully. Use `Jane Doe`, `Example Studio`, `scene one`, the
`alpha`/`beta`/`gamma` act placeholders the committed `content.example.json`
already uses. The near miss that still counts: taking a real filename and
changing a character or two — it is still that clip, still that performer. Make
it up from scratch, don't lightly edit a real one.

## One word per thing, and the two that keep their second

A word the code invents costs every later reader a translation, and four words
for one thing cost four. So:

- A submitted piece of work is a **job** (`JobQueue`, `GenerationJob`,
  `job_for`, `held_jobs`), from the press to the saved row. **Re-roll** is kept
  for the act it names -- a fresh variation of a settings folder, or a fresh
  seed on one row (`start_reroll`, `reroll_image_seed`, `reroll_video_seed`,
  `RerollTile`) -- and for nothing else; the class that owns every generation
  the app makes was called `RerollController` for years, and its own docstring
  had to say "it also *is* the queue" to undo the name. **Run** is only a
  chained job pair taken as a whole, which is what `origin` stamps. A
  **generation** is the saved row.
- Work started and not finished is **in flight** (`InFlightItem`,
  `InFlightCard`, `inflight_items`). "Cooking" said the same thing in fifty
  comments and is gone.
- On disk a waiting row's status is **pending**; on screen the line calls it
  **queued**. Both are right and `display_status()` is the one place that says
  so -- do not restate it in prose, and never change the string on disk.
- The **folder key** is the value; `gallery.keys.settings_key` builds one from
  its three parts and `gallery.tree.settings_folder_key` derives one from a
  row. Those are two questions with one answer, not two names for it. What was
  a real collision -- `GenerateConfigPanel.settings_key()` returning the *pair*
  a folder key is built from, one word from its own `settings_folder_key()`
  returning the key -- is `workflow_and_signature()`.
- **Settings**, **config** and **recipe** are three things and keep three
  words: the settings are what the form holds, a `ConfigSnapshot` is one
  reading of them, and a recipe is the workflow a generation ran on.

## The shared packages come from the install, at the versions `pyproject.toml` names

`app_support`, `player_core`, `shared_ui` and `voice_core` are pinned
dependencies installed into `.venv` — never the checkouts beside this one.
Both launchers run that venv and nothing else, and a Fun Time session starts
this app through it too. That venv is also every other agent's test runner,
so a branch never installs into it: to run a sibling version the venv does not
hold — an unlanded change, or a pin the branch moves — put a checkout of it
first on `PYTHONPATH` for the suite, and give the preview a launcher of its own
in the worktree's git-ignored `state/` that sets the same `PYTHONPATH`. A
player_core checkout used that way needs `vendor/libmpv-2.dll` copied in from
the primary player_core's `vendor/`. Moving a pin is this repo's own commit,
with its own suite to answer for it, and a new shared_ui release reaches this
app only beside a player_core release that names the same one: pip refuses an
install that asks for two tags of one sibling. Never reinstall `.venv` while
Origenerator or a Fun Time session may be running.

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

## An act keyword has to mean its act and nothing else in this library

`recipe_categories` in the content overlay decides which act a prompt depicts,
by plain substring, and that answer is now a name the user reads: a show's HUD
writes it into the gutter of every map row and onto that row's filter button
(`nav_map.act_of`). So a keyword that is also ordinary describing vocabulary
costs more than a wrong suggestion in Combine — it names rows for an act they
do not show, and the name they should have read, their folder's short code,
never appears at all. One such word — the act in one sense, a measurement of a
face in the other — sat in the quality boilerplate of 853 of this library's
3,884 pictures and named 472 rows for an act none of them shows, until the user
reported it off the map (2026-09-21); it is out of the overlay now.

So a keyword is measured against the library before it goes in: count what it
matches in the `positive_prompt` column of `state/origenerator.db` and read the
words around a sample of the hits. A word that fires inside the boilerplate
every prompt here carries is not distinctive, however plainly it names the act
elsewhere. The near miss that still counts: keeping such a word because some
prompts do mean the act by it — those prompts nearly always say so another way
too, which is what the act's other keywords are for, and a row has only one
name.

## A feature the session can reach is half a feature until Fun Time answers it

This app runs two ways — on its own, and hosted inside a Fun Time session as one
of the room's managed windows — so anything added here that the session touches
has a matching half over there, and the two are one piece of work rather than a
feature and a follow-up. Four shapes it takes: a verb in
`fun_time_bridge.py` (sent by fun_time's dispatch table and its loop branches;
`fun_time_mode.py` declares every line the command file answers and publishes
them in `origenerator_contract.json`, which fun_time's
`tests/test_vr_control_parity.py` holds everything its keys and phrases send
here to), a switch on the shared HUD in `gui/show_hud.py` (which posts a verb
`fun_time/tests/test_command_registry.py` holds the dispatcher to), the
`--fun-time` argv contract in `fun_time_mode.py` (built by fun_time's
`windows_bridge_startup.py`; that module declares the flags and the window
captions once and publishes them in the same document for the session to
read, and `tests/test_hosted_launch_contract.py` holds the parser and the
windows to what it says), and the offer, takeover and session-claim files
a standalone window meets a session through (`fun_time_mode.py` here,
`standalone_origenerator.py` there) — renamed on one side only, every session
quietly launches a second copy beside the one already open, and the copy it
missed goes on driving the OSR2 the session is driving too.

One-sided, none of them fails loudly. The console's enhanced-only switch shipped
on the shared side with nothing on fun_time's side answering the verb it posts,
so the button lit and the shows played on unchanged — a control that looks live
and does nothing, found by an audit rather than by a red test (bug 90). Pointed
the other way it is worse: a flag this app stops accepting is a flag the session
goes on passing, and the hosted launch dies in argparse before it can log.

The near miss that still counts: writing this side and filing the session's half
as an item for later. Both branches exist before either is pushed; which repo's
queue lands first is the only question, and it is answered by which order leaves
a live session working.

## The commands in `tools/`, and why each one is not a menu item

Two things live here that the app does not put in front of the user, so a
reader who never opens the folder will not find them. They are named here
because a command nobody can see is one nobody maintains — the base-render
backfill went a whole audit unreferenced by CLAUDE.md, CI, any launcher and any
test, which is how a script comes to re-implement a loop the app already owns.

The pre-publication content guard is no longer among them: it is
`app_support.sanitize`, published once for the family (backlog item 44), and the
harvester that learned its list off the media library is deleted. What is left
is the two hooks that call the guard, below.

- `tools/backfill_base_renders.py` — re-derives the base renders an inline
  enhance threw away, run to completion in one sitting instead of a few rows per
  absence. No `--apply` is a dry run and prints the count per workflow, which is
  the way to ask how much of that backlog is left. Everything it decides about a
  repair it asks `origenerator.base_backfill` — the same module the app's own
  absence path uses, down to the submit-and-wait — so the two cannot answer
  differently. Run it with the app closed; it is one full render per row.
- `tools/speech_worker.py` — the voice: speaks a story's scene lines with
  Qwen3-TTS, one WAV per scene at exactly the scene's length, from a JSON job
  `origenerator.speech` writes. Run by path under the `speech_python` the
  overlay names (Qwen3-TTS's pins would break this app's environment and
  ComfyUI's, so it has one of its own) and never imported by the package, which
  is why it lives here rather than in it: the dependency gate installs exactly
  what pyproject declares, and the voice's torch is not the app's to declare.
  `GenerationJob.start` runs it before a job with lines is submitted.
- `tools/githooks/` — `pre-commit` and `commit-msg`, both guarding the staged
  tree and the message with `app_support.sanitize`. Each is a shim that finds an
  interpreter which can import it and gets out of the way; neither has a way of
  not running that ends in a zero exit code. `install.py` points
  `core.hooksPath` here, which is the one step that arms a clone.

A new command here gets a line in this list and a test, or it is invisible by
the time anyone needs it.

## Judging a branch before it lands

Every worktree carries `launch_preview_branch.vbs` (tracked). Double-clicking it
runs THAT worktree's code as its own app instance: the primary checkout's venv,
and `ORIGENERATOR_BRANCH_SESSION=1`. Under that flag the app opens the **live
install's own library** — the primary checkout's database, thumbnails and trash
(`config.LIBRARY_STATE_DIR`) — so every instance, live or preview, shows every
generation whichever of them made it, and a delete in one is a delete in all;
only the window's own state and logs stay in the worktree's `state/`. What a
preview still leaves to the live app is ComfyUI's absence work — background
experiments and base re-renders, which would outlive it in a queue only the app
that queued them can cancel (see `origenerator/branch_session.py`). Before
handing one over, **re-copy the primary's `content.local.json` into the worktree
root every time**.

Re-copy, not copy-once. The overlay is where `project_roots` lives, and the
primary's library is found through it — a worktree carrying a copy taken weeks
ago, from before a root moved, resolves a primary that isn't there, and the
launch dies opening a database under a path that doesn't exist. The launcher
log's `Library: …` line names the path it tried; if a preview will not open,
diff the two `content.local.json` files before looking anywhere else.

**A preview replaces his everyday Origenerator; it never runs beside it.** One
copy runs on a library at a time, the way Fun Time runs one session (his call,
2026-09-25): a copy started while another holds the library -- the everyday one,
another preview, or the one a Fun Time session opened -- says "Another copy of
Origenerator is already running." and stops before its splash
(`origenerator/single_instance.py`). A preview he reports as not opening has
most likely met a copy already running, which that message names. A standalone
copy offers itself to Fun Time the moment it has the library, marked as still
starting until its window is up, so a session opened during its splash takes it
over and waits for it rather than starting a second (`fun_time_offer.txt`, read
by fun_time's `standalone_origenerator.py`). A copy Fun Time opens itself never
refuses, since refusing would leave the session's room with no Origenerator at
all; it is only ever opened when no copy has offered itself.

A change a Fun Time session reaches gets its hosted half judged too. Make a
fun_time worktree on fun_time's current `main`, put your Origenerator worktree's
path in its git-ignored `state/origenerator_dir.txt`, and run
`python -m fun_time.branch_session --shortcut` from it (fun_time's venv, with
`PYTHONPATH` at that worktree); the `Verify <branch>.lnk` it leaves in that
fun_time worktree, at the path it prints, is the second launch link. Bring that
worktree up to fun_time's
`main` again right before every handoff, though it carries no commits: the
launcher writes the session's config with the fun_time primary's current code,
so a worktree still on an older `main` dies reading that config before a window
opens. A key renamed on fun_time's `main` hours earlier did exactly that
(2026-09-13).

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
  launcher's own cwd, with nothing on `PYTHONPATH`, which is precisely what a
  dead icon fails at — and a launcher that breaks past that, he tells you about
  in one line.
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
dir's `origenerator.log` for "OSR2 motion engaged" / "streaming" to see whether
the app ever actually drove; lay a widget out offscreen and read its geometry
— `geometry()`, `sizeHint()`, where a child lands (`mapTo(window, QPoint())`)
once `layout().activate()` has run — never a picture of it, because a grab of
anything showing a generation is one of his pictures, which no agent looks at
(Private Content, in the global engineering law), and the private-content
hook refuses to open a PNG this checkout does not track; and check which
instance the user is running from the launch lines at the top of each state
dir's log — the "main app" can be on pre-merge code.

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
- **Never merge `main` into your branch. Rebase — and if that hurts, squash
  first.** The queue's merge method is REBASE, so a branch carrying merge
  commits is replayed as its *original* commits onto a `main` they were never
  written against: the same conflicts, again, on every attempt, with
  `github-merge-queue` evicting it each time "due to a conflict with the base
  branch". A branch that has drifted far collapses to one commit before it goes
  near the queue — `git reset --hard origin/main && git merge --squash <old-tip>`
  keeps the tree byte-for-byte and leaves a rebase with nothing to do. That
  costs a force-push, so do it before opening the PR, not after. The near miss
  that still counts: reaching for `git merge origin/main` because it resolves
  the conflicts *once* instead of once per commit — cheaper today, unlandable
  forever, and it compounds every time `main` moves again (one branch merged
  `main` three times and never landed).
- **`gh pr view` saying `CLEAN` does not mean the queue can land it.**
  `mergeStateStatus` answers whether a *merge* is clean; the queue rebases, and
  those are different questions. Check the one that decides: `git rebase
  origin/main` and see, or read the PR page, which says "This branch cannot be
  rebased due to conflicts" in plain words. One session spent an hour
  re-enqueueing a PR that `gh` called CLEAN and the bot evicted every time,
  because it only ever asked `gh`.
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
