"""What a branch session had bookmarked when the live app last adopted from it.

One of the six tables `Database` used to hold all of, and
`origenerator.branch_session` is its only reader. The items that worktree's
database starred, and its folder bookmarks: only what has *changed* there since
is applied at the next launch, so a star the user has removed here is not
reinstated on every launch by a worktree copy that still carries it, and an
unstar made in a preview crosses exactly once.

Keyed by worktree directory name; a row outlives its worktree harmlessly.
"""
import json

from origenerator.db_connection import Store


class BranchCurationStore(Store):
    """The two queries over the `branch_curation` table."""

    def branch_curation_state(self, branch: str) -> dict | None:
        """What was last adopted from the worktree named *branch*.

        ``None`` when this worktree has never been read — which is precisely what
        tells adoption it has no baseline to diff against, and so may add
        bookmarks but not take any away (see
        :func:`~origenerator.branch_session.adopt_branch_curation`). A record
        written by a future version and unreadable here counts as never read, for
        the same reason: guessing is what a missing baseline forbids.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM branch_curation WHERE branch = ?",
                (branch,),
            ).fetchone()
        if row is None:
            return None
        try:
            state = json.loads(row["state_json"])
        except (TypeError, ValueError):
            return None
        return state if isinstance(state, dict) else None

    def set_branch_curation_state(self, branch: str, state: dict):
        """Remember a worktree's bookmarks as of now, so the next launch can tell
        what the branch changed from what it merely inherited."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO branch_curation (branch, state_json, adopted_at)
                   VALUES (?, ?, datetime('now'))
                   ON CONFLICT(branch) DO UPDATE SET
                       state_json = excluded.state_json,
                       adopted_at = excluded.adopted_at""",
                (branch, json.dumps(state)),
            )
