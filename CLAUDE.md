
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

So fabricate fully. Use `Jane Doe`, `Sample Studio`, `scene one`, the
`alpha`/`beta`/`gamma` act placeholders the committed `content.example.json`
already uses. The near miss that still counts: taking a real filename and
changing a character or two — it is still that video, still that performer. Make
it up from scratch, don't lightly edit a real one.

## One word per thing, and the two that keep their second

A word the code invents costs every later reader a translation, and four words
for one thing cost four. So:

- A submitted piece of work is a **job** (`JobQueue`, `GenerationJob`,
  `job_for`, `held_jobs`), from the press to the saved row. **Re-roll** is kept
  for the act it names -- a fresh variation of a settings folder, or a fresh
  seed on one row (`start_reroll`, `reroll_image_seed`, `reroll_video_seed`)
  -- and for nothing else, the "+" that asks for one being the New tile
  (`NewTile`); the class that owns every generation
  the app makes was called `RerollController` for years, and its own docstring
  had to say "it also *is* the queue" to undo the name. **Run** is only a
  chained job pair taken as a whole, which is what `origin` stamps. A
  **generation** is the saved row.
- Work started and not finished is **in flight** (`InFlightItem`,
  `InFlightTile`, `inflight_items`). "Cooking" said the same thing in fifty
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
- **Settings** and **config** are two things and keep two words: the
  settings are what the form holds, and a `ConfigSnapshot` is one reading of
  them. **Recipe** is no word of the user's, and nothing here says it: a
  video's settings are its settings, the video a combine takes them from is
  its source video (`source_video`, as "From source video" under the form
  says), and the act a video was launched as is its `act`. Only names already
  stored keep the old word, each read under it in one place: the two
  `generations` columns, which only the database code names
  (`db_schema.STORED_NAMES`), the overlay's old keys
  (`content._RENAMED_KEYS`), the saved Model / LoRA sort (`search.saved_sort`),
  the accepted animation settings' file (`animation_settings.SETTINGS_PATH`)
  and the family stamp's keys (`provenance.WORKFLOW`, `WORKFLOW_VERSION`,
  `BASIS`). Never say it to him or put it in anything new.
- **The code's word is the one the app shows.** What the gallery shows as a
  video is a video in the code, an image is an image, and either one is an
  item. "Clip", said consistently all through the source, is a word the
  screen never shows: an agent who learned it here asked him about "a clip
  opened in a tab", and he had to ask what a clip was (2026-09-26). The
  audit's vocabulary pass above made each thing one word and never held the
  words against the screen, which is how "clip" passed it. Names that belong
  to something else keep theirs: CLIP the text model and its ComfyUI nodes,
  the clipboard, and Fun Time's Clip seconds. Genau's own videos are flicks
  in the code, and on screen they take the word the settings all of Haglio
  share give them, genau_flick_words.
- **An item is an image or a video, and neither is a picture or a record.**
  This code said "picture" all through it where it meant an image, and still
  says "record" where it means an item or the row behind one. Neither is the
  user's word, and an agent who reads them here says them to him: a
  loading-screen line read "Leaving one record per picture...", and he could
  not tell what it meant. So an agent says image, video and item, to him and
  on the screen. The code's "picture" became "image" (2026-10-25), and a
  picture that was no image took a name of its own: the small one on a tile,
  a row or a card is a **thumbnail**, one frame of a video or of this window
  sent to the headset is a **frame**, his drawings on the sorting window's
  buttons and the OSR2 console's drawing are **drawings**, and what a run is
  making, in the help for its settings, is the **result**. Saved names keep
  the old word and are read under the new one in one place each, as the
  recipe ones are: the `picture_state` column is `image_state`
  (`db_schema.STORED_NAMES`), an overlay's `picture_states` and
  `picture_state_grid` load as `image_states` and `image_state_grid`, a tab
  saved with a `picture_border` restores it as its `media_border`, and the
  folders of his drawings, `pictures_being_looked_over.json` and the
  `outside picture:` workflow names keep theirs. So do the saved names
  other repos own, each read under the new word there: Funestra's
  `HOLD_PICTURE`, a verb every running Funestra speaks, and app_support's
  loading screen's `pictures.json`.
- **Where the screen names nothing, the code takes the user's word.** The
  list of folders down the left of the gallery is the **TOC** (tree of
  contents, his word since 2026-10-30; table of contents before that), and
  the marks that open and shut its folders are its **carets**: no label
  names either, and those are the words the user and the app's designers use. So the code says `toc` and `caret`, an agent
  writing to the user says TOC and caret, and other names for the same two
  things -- tree, folder list, folder tree, arrow, chevron -- take nothing
  new. The back and forward buttons' chevrons and the text cursor's caret
  are other things, and keep their words. A folder with no folders inside
  it, and so no caret, is a **leaf folder**: the settings folders at the
  end of each path, which hold the items themselves.
- **A running Auto-Generate is Auto-Generate, never a loop.** Loop is the
  slideshow's word, for playing one row of its map over and over ("Loop
  off" says it stopped). The code called a running Auto-Generate "the
  loop", an agent repeated the word to the user, and he had to ask what it
  meant. So the code names it after the button, and so does every message
  to him.
- **The parts no label names have the user's names too, and an agent says
  them: HUD, Job Queue, Core and Standalone.** The **HUD** is the controls a
  Funestra draws over what it plays, a slideshow's included; the **Job
  Queue** is the list of jobs in flight or waiting, in Core and at the foot
  of a slideshow's HUD; **Core** is this app's main window, which a Fun Time
  session shows in the place of its Random Favs Browser (the **RFB**), one
  of the two hidden while the other shows; and
  **Standalone** is this app run on its own, outside a Fun Time session.
  The code says the same four: `hud` (`gui/slideshow_hud.py`, `Hud`), the
  Job Queue (`JobQueueView` in Core and `gui/hud_queue.py` on a HUD, with
  `JobQueue` the controller behind both), `core` (`gui/core.py`, `Core`) and
  `standalone`, and "panel" is left to the Generate, Enhance and Combine
  forms and the OSR2 console at Core's top left. So no agent reaches for
  another word: an audit that called the HUD a "panel", the Job Queue
  "the list of pictures and videos being made or waiting" and Standalone
  "on its own" left him asking whether each meant his word.
- **`glossary.json` lists the things on this app's screen and their words, and
  `tests/test_glossary.py` holds the code to it.** One row per thing: the word
  on the screen, the word the user says, the words the code says today, the one
  word the code is to say, and whether he has ruled. A noun the code reaches
  for to name a drawn thing (tile, card, badge, chip, scrim, plate, strip, cell,
  slot, pane, panel, console, band, toast, and the rest the test names) is a
  row there before it is a word in the code, so a new name is a row he rules
  on rather than a word an agent invents. A rename moves the old word from the
  row's `code_today` to its `retired`, which the test then holds at zero, and a
  row naming a code word the code no longer says is stale, which the test says
  too. A thing with no word of his yet has a row that says so, and the next
  piece of work on that thing asks him for one.

## The shared packages come from the install, at the versions `pyproject.toml` names

`app_support`, `funestra`, `shared_ui` and `voice_core` are pinned
dependencies installed into `.venv` — never the checkouts beside this one.
Both launchers run that venv and nothing else, and a Fun Time session starts
this app through it too. That venv is also every other agent's test runner,
so a branch never installs into it: to run a sibling version the venv does not
hold — an unlanded change, or a pin the branch moves — put a checkout of it
first on `PYTHONPATH` for the suite, and give the preview a launcher of its own
in the worktree's git-ignored `state/` that sets the same `PYTHONPATH`. A
funestra checkout used that way needs nothing copied in, since funestra finds
`libmpv-2.dll` in `%USERPROFILE%\.haglio\libmpv\` from any checkout, and is one
you made: another session's
goes when that session is done with it, and a suite that lost one partway on
2026-09-27 failed on `No module named 'player_core.mpv_player'`. Moving a pin is this repo's own commit,
with its own suite to answer for it, and a new shared_ui release reaches this
app only beside a funestra release that names the same one: pip refuses an
install that asks for two tags of one sibling. Never reinstall `.venv` while
Origenerator or a Fun Time session may be running.

## A model picker offers only what its graph can run

`ComfyUI/models/<category>` is a folder, not a catalogue. `checkpoints` holds WAN
and LTX video models beside the SDXL ones; `diffusion_models` holds WAN, Flux,
Qwen and bare SDXL UNets together; `loras` holds a LoRA for every one of those,
plus the occasional full checkpoint filed there by mistake. So a dropdown built
from a plain folder listing offers runs that can only error — and worse, presents
them as choices the user is being asked to make. That is exactly how the SDXL
T2I form came to show WAN 2.2's high/low expert pairs, with nothing to
say which one to pick or that neither belonged.

So every picker states what its graph runs: `model_dropdown(key, label, default,
folder, accepts=…)`, which lists that folder with `list_model_files(category,
fallback, accepts=…)` and keeps it on the picker, and `list_lora_files(fallback,
accepts=…)`, with `accepts` a family
from `workflows/model_arch.py`, a tuple of them, or `ANY` for a category that
genuinely takes anything (the ESRGAN upscalers). Add `expert="high"` / `"low"` on
a slot that fills one half of WAN 2.2's expert pair. `accepts` is keyword-only
with no default, so a new workflow cannot list a folder without answering the
question — forgetting is a `TypeError`, not a dropdown that quietly went back to
offering everything. Two registry-wide tests in `tests/test_workflows.py` cover
every workflow, present and future, so nothing here needs a name added to a list.

The families are read from each file's own header, never its name — installed
here is a checkpoint whose name says Flux and whose tensors say SDXL, and the
tensors are right. A WAN model's patch embedding says its kind too (16 channels
text-to-video, `ref_conv` Fun Control), so the image-to-video forms take neither,
and the SDXL graphs, which decode with the SDXL VAE, take no SD 1.5 checkpoint.
A WAN LoRA's header cannot say which of the two it was trained for, so there
the base model Civitai files it under decides (`base_models.json`, written by
`tools/record_from_civitai.py`), and one filed under text-to-video is left out
of the image-to-video forms too. A fix's own LoRA, in `loras\fixes`, is offered
in no LoRA dropdown but its own fix's prompts window, his decision (2026-10-29):
each fix's LoRA is trained for that fix alone. Krea 2 T2I's LoRA rows follow
the Model picked beside them (`ParamDef.beside_model`): a LoRA leaves them while
its base model and the Model's are both written down and neither is the other
or a kind of it (`base_models._KIND_OF`: Raw and Turbo are kinds of Krea 2, and
two kinds of it are apart). So the LoRA that turns Raw into Turbo, written down
by hand as made for Krea 2 Raw, is offered beside Raw alone (his decision,
2026-10-29).
**Unrecognized is not unwanted:**
`describe()` returns `arch=None` for a file it cannot read or match, and every
filter keeps those. Be wrong in that direction. A listed option that errors on
submit costs one run and says why; a working model missing from the dropdown has
no symptom at all, and the user cannot even tell there is something to look for.
The near miss that still counts: tightening a signature so an unfamiliar file
lands in a family rather than in `None` — a confident wrong answer hides the
model, where the honest shrug only leaves it listed.

## A model is shown by its title, and installing one gives it its title

The dropdowns, the TOC and the Enhancement Levels name a model or LoRA file by
its title (`model_titles.model_title`): the name its page on Civitai or Hugging
Face gives it, tidied, with the version, the expert half and the precision where
two files would otherwise read alike. Titles live in `model_titles.json` beside
the library's records (`config.MODEL_TITLES_PATH`), keyed by the file's name
without its extension, and outside the repo, since many of them name what the
library holds. A file with no title is shown by its name, and a fix's LoRA by
its fix and its version. So an agent installing a model writes its title
there in the same piece of work: the user asked for titles in place of
filenames (2026-10-24), and a model added without one is the filename again.

A title that ends in a number pair, "Example Look 1.0", is a base and a
version (`model_titles.versioned`), and every LoRA trained here is named
after the version that follows the highest its base already has
(`lora_versions.next_version`: 1.0, then 1.1, and so on), in the folder of
the version it follows, so no file is ever written over (his rule, 2026-10-25:
gallery records name the file). The fix LoRAs from before versions, named by
the minute they finished, keep their names and read as 1.0, 1.1 and so on in
the order they were trained. When a picked LoRA's title carries a version, its
dropdown's tooltip ends with the date its own header says it finished
training (`model_titles.trained_sentence`; kohya and musubi-tuner both write
it), on the settings form's LoRA rows and in a fix's prompts window alike,
which is where he chose to see it (2026-10-29). A trained look LoRA's title
and trigger words are written when the app takes the finished version
(`look_training.take`).
Installing a LoRA also writes down the trigger words it answers to and the base
model Civitai files it under, beside the titles in `trigger_words.json` and
`base_models.json`, by running `tools/record_from_civitai.py`; a LoRA trained
here gets its word written there by hand, from its training, and a base model
Civitai lacks or files too broadly is written there by hand too, which the tool
then leaves as it is.

## What a generation shows is said by hand, never read off its prompt

Two columns answer it and nothing else does: an image's `image_state`, set in
the sorting window or the Action list on a Generate tab, and a video's
`act`, the act picked when it was launched. `act_settings.act_of`
reads those two and returns "" for a row nobody has said one for, which a
slideshow's map draws as a row with no act name, in its gutter and on its filter
button (`nav_map.act_of`).

It used to be worked out from the prompt, by matching each act's keywords in
`acts` against the stored text. That answer named every map row and
narrowed the show's act filter, and it was wrong often enough to be worse than
nothing: it named rows for an act none of them shows, which the user found off the map
(2026-09-21). He called the mechanism garbage and had it removed, with the spoken
"genau it" that animated an image as whatever its prompt read as (2026-09-22).
`acts` is now a plain list of the act names.

So nothing in this repo may go back to guessing from a prompt, however tempting a
blank row looks: a blank says the image has not been sorted, which is a thing to
fix in the sorting window, not in code. The near miss that still counts: a
"fallback" that reads the prompt only when the hand-set answer is missing — that
is exactly the shape that was removed, and it leaves one question with two
answers again.

## Where ComfyUI saves, and how an output reaches the library

ComfyUI saves into a folder of its own (`comfyui_output_dir` in the settings
all of Haglio shares), outside the library, and refuses to save into or read
from anything a link inside that folder points at (its realpath check, since
2026-07-02). So each run saves into `origenerator/<prompt id>/` there
(`library_filing.saving_into_its_run_folder`; a past output or picked image
the run reads reaches ComfyUI the way every file kept outside its folders
does, as a copy in its temp folder, `comfyui_inputs`), and completion files
each finished file into the library folder its kind is kept in (`file_into_library`; the kinds are `OutputPlaces`, read from
the settings), numbered after the highest number already there or held in
Trash. That last part is his rule (2026-10-24): a name another item had is
never given out while that item can come back, and a skipped number is
fine. A file put back from Trash whose name a newer file has anyway comes back
under the next free number, and its item lists that name, so no two items ever
list one file. A record keeps naming its file by kind (`image`, `video`, ...), so
every row made before this resolves unchanged.

A run's folder names its run, so what is saved there reaches the library only
on that run's own row: a run ComfyUI finished and then forgot (it forgets every
run when it restarts) is written down at launch from what its folder holds
(`inflight.reconcile_in_flight`), and nothing else ever moves a run's files.
What a run left with no row to take it -- one canceled that ComfyUI finished
anyway -- stays where ComfyUI saved it, because the import writing a run of
this app's down as an item of its own is how four videos lost their start
images in October 2026: the item it made names ComfyUI's temporary copy of the
start image. At launch `file_what_comfyui_left` files only what another program
left in ComfyUI's folder.

That folder still holds four links from the old scheme (`image`, `video`,
`audio`, `funscript`, into the library). ComfyUI refuses them, nothing of this
app's uses them, and they stay for a checkout older than this change: such a
copy resolves its records through them, and with them gone, the first real
folder of those names that a save created would read to its startup repair as
every image having vanished from a folder that still holds files. Removing
them is safe only once no checkout that old can be started.

## A video's filename is not the video

A finished video is numbered after the highest number in the folder it is filed
in or held in Trash, so a deleted video's filename goes to a later one once
Trash has let the deleted one go, and two videos
can share a name: in two folders, or in one folder as an mp4 and a webm. So a
script is filed where its video is, under the video's whole filename
(`funscript_path_for`), and moves with the video when the app follows a move;
completion writes each finished video's script over whatever was filed there.
Older scripts are filed by the name without its type, or beside the video, and
anything that carries one of those to a video by name -- a copy into Evolver's
library, say -- first checks that the two are the same length. A one-off copy
of this folder's scripts into the library on 2026-09-26 did not, and a video
from April on the Satellites was given the script of a June video that had
since taken its name.

## A feature the session can reach is half a feature until Fun Time answers it

This app runs two ways — Standalone, and hosted inside a Fun Time session as one
of the room's managed windows — so anything added here that the session touches
has a matching half over there, and the two are one piece of work rather than a
feature and a follow-up. Four shapes it takes: a verb in
`fun_time_bridge.py` (sent by fun_time's dispatch table and its loop branches;
`fun_time_mode.py` declares every line the command file answers and publishes
them in `origenerator_contract.json`, and fun_time publishes every line, launch
flag and headset word it sends here in its `tests/origenerator_expectations.json`,
which `tests/test_fun_time_expectations.py` holds this app to before it ships --
so a line, flag or word fun_time still sends is retired on fun_time's side
first), a switch on the shared HUD in `gui/slideshow_hud.py` (which posts a verb
`fun_time/tests/test_command_registry.py` holds the dispatcher to), the
`--fun-time` argv contract in `fun_time_mode.py` (built by fun_time's
`windows_bridge_startup.py`; that module declares the flags and the window
captions once and publishes them in the same document for the session to
read, and `tests/test_hosted_launch_contract.py` holds the parser and the
windows to what it says), and the offer, slideshow, takeover and session-claim
files a standalone window meets a session through, which both apps write and
read through `app_support.origenerator_handoff` and nothing else, so a change
to them is one change there and a pin both apps move -- written by one app on
its own, every session quietly launches a second copy beside the one already
open, and the copy it missed goes on driving the OSR2 the session is driving
too. The claim is also
a matter of where: a preview keeps a `state/` of its own, so it reads the
claim in the production copy's `state/` as well, which is where every session
writes one; a preview that read only its own went on driving beside Fun Time
(2026-09-26).

One-sided, none of them fails loudly. The console's enhanced-only switch shipped
on the shared side with nothing on fun_time's side answering the verb it posts,
so the button lit and the slideshows played on unchanged — a control that looks live
and does nothing, found by an audit rather than by a red test (bug 90). Pointed
the other way it is worse: a flag this app stops accepting is a flag the session
goes on passing, and the hosted launch dies in argparse before it can log.

The near miss that still counts: writing this side and filing the session's half
as an item for later. Both branches exist before either is pushed; which repo's
queue lands first is the only question, and it is answered by which order leaves
a live session working.

Every copy of this app that can run is a surface too, a preview included, and
a handshake with Fun Time has to work whichever copy of each app is running.
A preview runs its worktree's code with a `state/` of its own, so a file one
app writes into one checkout's `state/` for the other to find reaches only the
copy that runs from there, and a preview that reads only its own goes on
driving the OSR2 beside the session that took the device over. So anything
one app tells the other about the one device, the one library or the one
machine is written to the everyday checkout's `state/`, which previews already
share for their library, and read from there by every copy; and a change to
such a handshake is tried with a preview on each side before it is called
done. The near miss that still counts: a fix that reaches the previews built
after it and says nothing about the ones already handed over, which read only
their own `state/` until their branches are brought up to date.
## Two windows of this app's that the app has no button for

Both are launched from a `.vbs` of their own beside `launch_origenerator.vbs`,
both run the primary's venv with `ORIGENERATOR_BRANCH_SESSION=1`, and both read
and write the LIVE install's library from whichever checkout starts them
(`config.LIBRARY_STATE_DIR`). That last part is deliberate: a branch's own
database is one nobody will ever animate from, so a run of either spent on it
would be lost. `tests/test_launcher_contract.py` holds both to that.

- `sort_images.vbs` -> `origenerator.sort_images` -- says what each image
  shows, a press apiece. The vocabulary is the overlay's `image_states` and
  the answer lands in the row's `image_state`; which images are still
  waiting and in what order is `image_sorting`, what each press does is
  `sorting_session`, and the window is `gui/sorting_window.py`. Each state's
  button wears the user's own drawing of it, found by `action_drawings` in the
  running copy's own `state/picture_states/` and then the live install's: his,
  and library subject matter, so
  they are as uncommittable as the state names and live beside the library.
- `check_animations.vbs` -> `origenerator.check_animations` -- settles what each
  of the overlay's `animation_paths` entries runs, one at a time, against a video
  the user already kept. `animation_samples` finds and orders them,
  `animation_check_session` is the walk, `gui/animation_check_window.py` is the
  window, and what is accepted goes to `animation_settings` -- one set of
  settings per (lane, act, image state) in a file of its own beside the library, which
  `CombineController._curated_combination` asks before the overlay's per-act pin.

  That per-act pin is on its way out, by the user's decision: it answered for a
  whole act whatever the image showed, and it did not animate well enough to
  keep. So nothing new may be built on it or around it -- no editor for it, no
  second place that writes it -- and the end state is settings per (lane, act,
  image state) and nothing else. Until every one of those is settled it stays
  as one thing only: the starting position the window offers for an animation
  nobody ever kept a video of, which is the last place `starting_point` looks.

Neither can answer anything the other has not: an animation's samples are videos
made from images already sorted, so the sorting window comes first and a fresh
library shows every animation blank.

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
- `tools/fix_lora_trainer.py` — trains a fix's LoRA in two steps, each run by
  path under the Python that can do it. `crop` cuts each photo in that fix's
  folder under `app_data\origenerator\fix photos` down to the part with the
  fix's own detector, under the Python ComfyUI runs on, which ComfyUIApp's
  launcher names (`comfyui_python()`): that is the one environment certain to
  read every detector a fix uses, since a fix's detector is ComfyUI's model,
  and a copy of ultralytics anywhere else falls out of step with it -- the training
  environment's could not read a newer detector on 2026-10-21, and the training
  died before it touched a photo. `run` is the whole training, started by the
  Train button under the `lora_training_python` the overlay names (sd-scripts'
  pins are not this app's to declare, the same reason as the voice's): it starts
  `crop`, then runs kohya's sd-scripts on the crops into ComfyUI's `loras\fixes`.
  Both print into the run's `training.log` and leave their word, a failure's
  reason included, in its `status.json`; `process.json` names the program, so
  any launch can tell a training still running from one that ended. A training
  goes on when the app closes, as a run in ComfyUI does: nothing is handed to
  ComfyUI while it runs (on 2026-10-21 a close handed ComfyUI the line a training
  held, the two fought over the graphics card and the training ran out of
  memory), the next launch holds the line for it again, and the watcher left at
  closing announces its end.
- `tools/look_lora_trainer.py` — trains the next version of a look LoRA on
  Krea 2 with musubi-tuner, under the `krea2_training_python` the overlay
  names (musubi's pins are not this app's either), from the Train button beside
  a LoRA row whose pick is one of the overlay's `trainable_loras`
  (`origenerator/look_training.py`). Its steps, each a subcommand on the same
  job file: `prepare` copies the folder's pictures in as JPEGs named by their
  contents, so an unchanged picture keeps its copy and its description across
  trainings; `describe` writes a description beside each new copy with
  Florence-2, in a program of its own so the model leaves the card before the
  training; `dataset` puts the recorded trigger words in front of every
  description, the words the entry's `trigger_words` names (a version's own
  recorded words only when the entry names none); `cache` and `train` run
  musubi's own programs, the training only while ComfyUI's line has been
  empty two minutes and the card's memory is back, stopped the moment ComfyUI
  has a job and resumed from its newest saved state, since his own
  generations come first (his rule); `install` copies the result beside the
  newest version as `<base> <version>` and never over a file. It works in
  `state/lora training/<base>`, outside the library, because pCloud turns a
  state rewritten every 25 steps into conflicted copies. It prints counts,
  never a description or a picture's name. The queue only watches this
  training (`TrainingRun.holds_the_line`), where a fix's holds it.
- `tools/card_claim.py` — the one claim on the graphics card, the file
  `~/.haglio/graphics_card_claim.json` naming who holds it and its Windows
  pid. Both trainers take it before they use the card and let go when they
  stop, his hand training scripts beside the library take and honor the same
  file, and a claim whose pid has died is stale: two trainings each yielding
  only to ComfyUI's line took the card together on 2026-10-29 and both crawled.
- `tools/open_from_toast.py` — what Windows runs when a toast of
  this app's is clicked, registered as the command for the `origenerator:` link
  every toast carries. It hands the generation to the copy that has the
  library if one is open, a preview included, and starts production
  Origenerator on it if none is; `origenerator.app_link` is all of the
  deciding, and the registering is `Toasts`. Every copy registers the
  production checkout's, his decision (2026-10-18): a toast opened the preview
  that had raised it, and he wants toasts to open production. So a change to
  what this handler decides reaches a click only once it ships, and a preview
  shows only what an open copy does with the item it is handed.
- `tools/record_from_civitai.py` — asks Civitai, by each file's SHA-256, for
  the trigger words and the base model of every installed LoRA missing either,
  and the base model of every model in `checkpoints` and `diffusion_models`
  missing one (what a LoRA row following its Model compares a LoRA's against),
  and writes each one only where it is missing, in `config.TRIGGER_WORDS_PATH`
  and `config.BASE_MODELS_PATH` beside the titles: `[]` and `""` for one
  Civitai does not know, so a later run skips it, and a fix's own LoRAs are
  left out. A file several versions list answers with the version it is the
  main file of. It prints counts, never a name or a word. Run it from the
  production checkout, where those paths are the library's files.
- `tools/githooks/` — `pre-commit` and `commit-msg`, both guarding the staged
  tree and the message with `app_support.sanitize`. Each is a shim that finds an
  interpreter which can import it and gets out of the way; neither has a way of
  not running that ends in a zero exit code. `python -m app_support.githooks`
  points `core.hooksPath` here, which is the one step that arms a clone.

A new command here gets a line in this list and a test, or it is invisible by
the time anyone needs it.

## A change to how a video is scripted is finished by the sweep

A video's funscript is synthesized once, when the video finishes. So a change to
the pace (`config.MOTION_DEFAULT_SPEED`) or to what `synthesize_actions` writes
reaches only the videos made after it lands, and the library goes on moving the
device the old way: when the pace came down from 72 cycles a minute to the Robot
Hand's 29, the user had to ask for the videos he already had to follow
(2026-09-21). `origenerator.funscript_backfill` is what carries such a change
back: it rewrites every script that is one of the app's own metronomes at
another pace, writes one for any video with none, and leaves alone every script
that follows its own video — ATI's, a measured one, a hand-made one — which it
tells apart by shape, since most of the library's scripts predate the creator
stamp. Run it once when such a change lands, from the production checkout, as
`python -c "from origenerator.funscript_backfill import main; main()"`: spelled
with `-m` it names the package first, and the hook that keeps the app's window
off his screen refuses it.

## A setting a person can change comes back after a restart

Origenerator keeps every setting a person can change in one place and brings
it back at the next launch, the way Fun Time does. The one place is the
window's session, saved in `state/ui_state.json` through one table,
`SESSION_UI_STATE` in `gui/core.py`: a key, what the view is asked for
on the way out, what it is told on the way back in. A control added without a
line there is forgotten at every launch with nothing failing, which is how
Separate and Together, Images / Videos / Both, the folders left open in the
TOC, the console's Speed, Amp, Center, shape and Human inspired, every
dragged border and each tab's folded sections went unremembered until the
user noticed one of them.

`tests/test_remembered_settings.py` holds the window to it the way Fun
Time's `test_session_resume.py` holds the session: it builds the window,
counts every control a person can set and every press and bar on the
console, and fails on one that neither a key of the table nor its short list
of things that are no setting accounts for. So a new control is finished
when it has its key, or its line there saying why it is no setting -- what is
being searched for, what one image shows, a nudge, and Auto-generate, which
a restart leaves off, since an Auto-Generate that came back on by itself
could run unnoticed.

Inside a Fun Time session the window draws what the session asks for -- one
list per shape, its own borders held still, the room's device and sound --
and leaves the standalone choices it overrides as it found them, so a window
handed back, or the next launch in Standalone, is where he left it.

## Judging a branch before it lands

Every worktree carries `launch_preview_branch.vbs` (tracked). Double-clicking it
runs THAT worktree's code as its own app instance: the production checkout's
venv, and `ORIGENERATOR_BRANCH_SESSION=1`. Under that flag the app opens the
**production app's own library** — the production checkout's database
(`config.LIBRARY_STATE_DIR`) and the thumbnails and trash kept in the library
itself (`config.RECORDS_DIR`) — so every instance, production
or preview, shows every generation whichever of them made it, and a delete in
one is a delete in all; only the window's own state and logs stay in the
worktree's `state/`. What a preview still leaves to the production app is
ComfyUI's absence work — background experiments and base re-renders, which
would outlive it in a queue only the app that queued them can cancel (see
`origenerator/branch_session.py`). Before handing one over, **copy the
production checkout's `state/ui_state.json` into the worktree's `state/`, every
time**: that is what was open in the gallery, and without it a preview opens on
nothing and reads as a dummy -- which is what a Fun Time session handed him on
2026-09-20, and why fun_time's `--shortcut` now refuses a hosted checkout that
has neither.

Re-copy as the LAST step before the link goes out, and then import the window
chain against that copy (`from origenerator.gui.core import
Core` in a fresh interpreter, no `PYTHONPATH`): `tests/
test_launch_smoke.py` deliberately stands the committed sample in for the
local overlay, because a public checkout has only the sample, so it cannot
see a local overlay the code can no longer read. A copy taken two hours
earlier met exactly that on 2026-09-26 -- the overlay's act list went from a
list to a table of keywords on the machine 23 minutes after the copy, and the
preview died at import with a loading screen that never lifted.

Where the checkouts and the library are (`project_roots`, `library_root`) is
read from `~/.haglio/settings.json` by every copy, previews included, so no
overlay copy can send a preview looking for a primary that isn't there. The
launcher log's `Library: …` line names the path it tried.

A branch that leans on a sibling change that has not landed cannot be judged
through `launch_preview_branch.vbs` alone: that launcher runs the pinned venv,
which holds the siblings at the versions `pyproject.toml` names and nothing
newer. Give such a worktree a launcher of its own in its git-ignored `state/`
that puts the sibling's checkout first on `PYTHONPATH`, the way a hosted
launch already does, and never reinstall the shared venv for a preview, since
other sessions' suites run out of it. Every sibling such a launcher puts on
`PYTHONPATH` comes from a checkout held at the version the branch needs -- the
sibling branch's own worktree for the unlanded change, a worktree at the
pinned tag for any other -- never from a primary checkout, which every landing pulls forward under
the launcher until the link dies on import before a window appears. And before
that link goes out, replay the launch's imports under the launcher's own
environment: `tests/test_launch_smoke.py` strips `PYTHONPATH` on purpose, so a
green run of it cannot see what such a launcher loads.

**A preview replaces his production Origenerator; it never runs beside it.** One
copy runs on a library at a time, the way Fun Time runs one session (his call,
2026-09-25): a copy started while another holds the library -- the production one,
another preview, or the one a Fun Time session opened -- says "Another copy of
Origenerator is already running." and stops before its splash
(`origenerator/single_instance.py`). A preview he reports as not opening has
most likely met a copy already running, which that message names. A standalone
copy offers itself to Fun Time the moment it has the library, marked as still
starting until its window is up, so a session opened during its splash takes it
over and waits for it rather than starting a second (the offer in
`app_support.origenerator_handoff`). A copy Fun Time opens itself never
refuses, since refusing would leave the session's room with no Origenerator at
all; it is only ever opened when no copy has offered itself.

A change a Fun Time session could show differently gets its hosted half judged
too. A session draws this same window at its own smaller scale, reaches it with
its own keys and spoken commands, and runs code only a hosted window runs, so a
change to a size, to a key or a command, or to hosted-only code owes a Fun Time
launcher beside the standalone one: bigger toolbar marks handed over in a
standalone preview alone were sent back for exactly that. A change that looks
and works the same at any size and in either host, such as taking the dim off a
image under the not-yet-generated line, goes out with the standalone preview
alone; a second launcher would only ask him to accept it twice. When the hosted
half is owed, make a
fun_time worktree on fun_time's current `main`, put your Origenerator worktree's
path in its git-ignored `state/origenerator_dir.txt`, and run
`python -m fun_time.branch_session --shortcut` from it (fun_time's venv, with
`PYTHONPATH` at that worktree); the `Verify <branch>.lnk` it leaves in that
fun_time worktree, at the path it prints, is the second launch link. Bring that
worktree up to fun_time's
`main` again right before every handoff, though it carries no commits: the
launcher writes the session's config with the production fun_time checkout's
current code, so a worktree still on an older `main` dies reading that config
before a window
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
  popping up unannounced, which he closes in irritation, and his production app
  goes with it (both instances I launched and his running app were gone inside two
  minutes, 2026-08-15; he asked for this law by name). Launching is HIS act, on
  his schedule. This overrides the older "launch it once yourself to confirm it
  comes up clean" rule, which is what produced the failure. The pre-handoff
  check is windowless instead: `python -m pytest tests/test_launch_smoke.py`
  replays the launch's whole import phase in a fresh interpreter under the
  launcher's own cwd, with nothing on `PYTHONPATH`, which is precisely what a
  dead icon fails at — and a launcher that breaks past that, he tells you about
  in one line.
  `~/.claude/hooks/block-visible-origenerator.py` blocks the visible launch
  mechanically, so this one does not rest on prose. Same reason his production
  app must never be closed by you — every Origenerator window is a `python` process
  titled "Origenerator", so a title-matched close shuts his app too
  (2026-08-13). The near miss that still counts: launching it "just for a few
  seconds" to read `state\origenerator_launcher.log` — those seconds are the
  window on his screen, and that is the whole failure.
- Hand a launcher link to the vbs FILE itself — never its folder,
  never a shell command, and never any launcher sharing a filename with the
  production app's. The user was once handed the worktree's `launch_origenerator.vbs`
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
from a session, no hardware in view: have an
`origenerator.osr2.Osr2Broker` `want(True)` and `send_position` a few times, then
stat `../fun_time/state/osr2_serial_tx.txt` (its mtime moves iff slot → broker →
serial happened; `broker_heartbeat.txt` is broker liveness); grep each state
dir's `origenerator.log` for "OSR2 motion engaged" / "streaming" to see whether
the app ever actually drove; lay a widget out offscreen and read its geometry
— `geometry()`, `sizeHint()`, where a child lands (`mapTo(window, QPoint())`)
once `layout().activate()` has run — never a grab of it, because a grab of
anything showing a generation shows his images and videos, which no agent looks at
(Private Content, in the global engineering law), and the private-content
hook refuses to open a PNG this checkout does not track; and check which
instance the user is running from the launch lines at the top of each state
dir's log — the "main app" can be on pre-merge code.

A script that builds the gallery outside the suite holds the real OSR2 and
the real Origenerator Radio: `GalleryView` makes its own `Osr2MotionDriver` and
`OrigeneratorRadio` unless it is handed them, and a restored session turns both
back on. A walk through the folder path, run that way on a copy of the
library, moved the device for a fifth of a second twice while the user was
using it, through a key sent to a window that was never shown and activated.
So such a script replaces the drivers' broker and tick thread and the
radio's start the way `tests/conftest.py` does, and shows and activates its
window before it sends a key. The near miss that still counts: cutting off
the sound alone, since a restored session brings the OSR2 switch back with
it.

## Landing — GitHub merge queue, not local ff-merge

This repo is public at `github.com/haglio/origenerator` with a merge-queue ruleset on
`main`, so the global "ff-merge into the production checkout under
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
  the production checkout, don't push `main` directly, and never force-push `main`.
- **Never merge `main` into your branch, and never collapse its commits into
  one. Always rebase, resolving each conflict in the commit it belongs to.**
  Each commit's message is the record of why, and one commit in place of many
  throws that away. The queue's merge method is REBASE, so a branch carrying merge
  commits is replayed as its *original* commits onto a `main` they were never
  written against: the same conflicts, again, on every attempt, with
  `github-merge-queue` evicting it each time "due to a conflict with the base
  branch". A branch already on origin that a rebase rewrites goes up under a new
  name with a pull request of its own, since nothing here is ever force-pushed.
  The near miss
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
- **The production updater moves the primary checkout; never pull it or install
  into its venv yourself.** `main` advances only on origin (via the queue), and
  app_support's production updater brings the primary checkout and its venv up
  to it, the libraries it pins first, as soon as nothing of his runs from it;
  every launcher here does the same just before it starts Origenerator. So a change
  reaches him the next time he opens Origenerator, and worktrees update with
  `git rebase origin/main`. A hotfix he asks for goes ahead of that only through
  the hotfixing skill's route, which runs the checks `[tool.haglio.hotfix]` names.
- **A red required check** (`.github/workflows/merge-gate.yml`) can't land.

Everything else in the global CLAUDE.md — work in a worktree, green tests before
you push, clean handoff — still applies.
