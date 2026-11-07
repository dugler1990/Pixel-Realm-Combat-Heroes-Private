# Working on a branch in its own folder

Several agents work on this repo at once. A folder has one checked-out branch, so a `git switch` in
`C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private` moves every agent working there, and their
uncommitted edits ride along onto whatever branch is now checked out.

A **worktree** gives a branch its own folder. It is not a clone: it shares this repo's `.git`, so a
commit made in either folder is in both at once. One branch per folder, one agent per folder.

When the user says "follow docs/WORKTREES.md for <task>", do the steps below in PowerShell from the
main folder. `<task>` is a short name such as `legion-ui`; use the branch prefix the repo uses for
that kind of work (`feat/`, `fix/`, `perf/`, `refactor/`).

## 1. Make the folder

```powershell
git worktree add -b feat/<task> ..\Pixel-Realm-<task> main
```

It starts from `main`. `git worktree list` shows every folder and the branch it has.

## 2. Link what git doesn't carry

A new worktree has only the tracked files. Link in what the task needs; don't copy, and never link
the keys (`ppp`, `ppp.pub`).

- **The venv**, to run the game or the tests, as a junction:

  ```powershell
  New-Item -ItemType Junction -Path ..\Pixel-Realm-<task>\Code\sprite_venv -Target "$PWD\Code\sprite_venv"
  ```

- **The painted level art**, to run a level (70 files, 1.5 GB), as hard links. They take no extra
  space on the same drive:

  ```powershell
  $wt = "..\Pixel-Realm-<task>"
  git ls-files --others --ignored --exclude-standard levels | ForEach-Object {
    $to = Join-Path $wt $_
    New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null
    New-Item -ItemType HardLink -Path $to -Target (Join-Path $PWD $_) | Out-Null
  }
  ```

  Swap `levels` for another path, such as `generated\building_interiors`, to bring a pipeline's
  working files. A hard link is the same file in both folders: a tool that edits it in place changes
  it in both.

## 3. Start the agent there

Run `code ..\Pixel-Realm-<task>` and start the agent in that window. An agent works in the folder it
starts in. Claude Code keeps its memory per folder: if the new session doesn't show the project's
memory, tell it to read
`C:\Users\Douglas\.claude\projects\c--Users-Douglas-Pixel-Realm-Combat-Heroes-Private\memory\MEMORY.md`.

## 4. Commit and push from that folder

```powershell
git push -u origin feat/<task>
```

## 5. Merge into main

In the folder that has `main` checked out (see `git worktree list`; if none does, run
`git worktree add ..\Pixel-Realm-main main`):

```powershell
git merge --no-ff feat/<task> -m "Merge feat/<task> into main."
git push origin main
```

## 6. Remove the folder

After the merge:

```powershell
cmd /c rmdir ..\Pixel-Realm-<task>\Code\sprite_venv   # removes the junction, not the venv
git worktree remove ..\Pixel-Realm-<task>
git branch -d feat/<task>
```

Removing the folder deletes only the hard links; the art stays in the main folder.

## Rules

- Before editing, run `git branch --show-current` and check you're in your own folder.
- Don't `git switch` or `git checkout` in a folder another agent may be using; ask the user first.
- git won't check out a branch that's already checked out in another folder. That's the point.
