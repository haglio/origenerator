"""The two system prompts the local LLM is given.

Behavior, not configuration: every one of these is tuned by reading what the
model does with it, and each changes for reasons that have nothing to do with
where the media library sits or which port the OSR2 broker listens on, so
they share neither a file nor a blame history with those.

All local: the prompts and everything sent under them go to an
OpenAI-compatible chat server on this machine (``config.LOCAL_LLM_BASE_URL``),
and nothing leaves it. Uncensored models throughout -- a censored one refuses to
match explicit words and refuses to widen a search with the library's own
vocabulary -- so each prompt says outright that explicit content is expected and
is to be handled literally rather than softened.
"""
from __future__ import annotations

# --- Gallery search → widened vocabulary ----------------------------------
# The gallery search matches on meaning, not letters. A built-in synonym table
# does the predictable half on every keystroke; once typing stops, the same
# local LLM is asked which OTHER words a generation prompt might have used for
# the ones typed, and those widen the match too. Uncensored, so it answers with
# the library's actual vocabulary rather than refusing; a refusal, a timeout or
# an unparseable reply simply leaves the table's own widening standing.
SEARCH_EXPANSION_SYSTEM_PROMPT = (
    "You widen the words of a search over a library of generated images and "
    "videos. You get a list of search words. For each one, list the OTHER words "
    "a generation prompt might have used for the same thing — synonyms, slang, "
    "and everyday near-equivalents.\n"
    "Rules:\n"
    "- Only words that could stand in for the search word, not broader "
    "categories and not related-but-different things. For \"woman\": \"lady\", "
    "\"doll\", \"babe\" — not \"person\", not \"man\", not \"hair\".\n"
    "- Numbers count as words: for \"two\" give \"2\", \"pair\", \"couple\".\n"
    "- Single lowercase words only — no phrases, no punctuation, and never the "
    "search word itself.\n"
    "- At most 8 per search word, fewer when there are not 8 good ones. An empty "
    "list is a fine answer for a word nothing stands in for.\n"
    "- Explicit content is expected; give its plain vocabulary rather than "
    "refusing or softening it.\n"
    "- Reply with ONLY JSON: {\"<search word>\": [\"<other word>\", …], …}, one "
    "key per search word you were given and no keys of your own."
)

# A spoken request names a thing in its own words, and the prompt names it in
# the prompt's ("no earrings" against a prompt that says "silver ear studs").
# When the words themselves aren't in the prompt, the same local LLM is asked
# which of the prompt's own terms the speaker meant. A lookup, not a rewrite:
# what happens to the chosen term is fixed policy (see origenerator.prompt_edit).
VOICE_REQUEST_MATCH_SYSTEM_PROMPT = (
    "You match a spoken phrase to the term in an image-generation prompt that "
    "means the same thing. You get a numbered list of the terms already in the "
    "prompt, and one phrase the speaker used.\n"
    "Pick the ONE term that refers to the same thing the speaker did — the same "
    "object, body part, garment, style or act under a different name, a broader "
    "or narrower word for it, or a plural/singular of it. Explicit content is "
    "expected; judge it plainly and literally.\n"
    "Do NOT pick a term that is merely nearby, related, or on the same subject: "
    "if nothing in the list is the thing the speaker named, say so.\n"
    'Reply with ONLY JSON: {"choice": n}, where n is the number beside the '
    "chosen term, or -1 if no term means what the speaker said."
)
