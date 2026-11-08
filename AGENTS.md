# Working in this repo

Several agents (Claude Code and Cursor) work here at once. These rules keep the repo clean
and leave the user in charge of it.

## Leave the repo as you found it
- Before you finish, run `git status` in every folder you touched. It must show only what you
  mean to leave there: nothing uncommitted that is yours.
- No leftovers: no uncommitted copies of work you committed elsewhere, no stashes, no scratch
  files in the repo, no half-done merges.
- If you can't leave it clean, stop and tell the user what is left and why.

## Your work, your branch, your folder
- Work on your own branch in your own worktree ([docs/WORKTREES.md](docs/WORKTREES.md)). Never
  edit files in a folder that has another branch checked out.
- Changes you didn't make belong to someone else. Never stage, commit, stash, reset, discard
  or delete them.

## Ask before changing shared state
- Get the user's go-ahead before: switching a branch in a shared folder, stash, reset, clean,
  discarding changes, deleting files you didn't create, merging, pushing, rewriting history.
- A question is not an instruction. When the user asks how to do something, answer it; don't
  do it.
- If the normal way is blocked (a folder is busy, a merge conflicts), stop and say so. Don't
  get around git with low-level commands (`commit-tree`, `update-ref`, temporary index files).
- Facing a decision about how the repo is handled (a workaround, leaving something behind):
  stop and tell the user first.

## Process docs
Every initiative keeps one: `PROCESS_*.md` or `NOTES_*.md` in its folder. Read it before
starting. Terse lines, no narrative: facts, commands, numbers.
- **Method that works**: exact steps, commands, settings to repeat.
- **Tried and dropped**: idea, result, why. Don't retry these.
- **Known errors**: symptom, cause, fix.
- **Log**: dated steps, commands, numbers.

Maintain it as you go, don't just append: a retry with small changes merges into its existing
line; a wrong claim is replaced; what proved out moves into Method.

## Say exactly where things stand
- End every task with: the branch, its commits, what is pushed, and anything left uncommitted
  and whose it is.
- Report checks as they were done: what you compared and how, not just "verified".
