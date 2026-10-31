"""The screen a paid generation step shows before you pay for the next one.

The interior walkthrough and the entity pipeline both print from here, so the two pipelines
show the same thing. Standard library only: the entity pipeline imports this module, and it
must not load cv2 or the interior walkthrough.
"""
from __future__ import annotations

import os
from pathlib import Path


def ask(question, default=""):
    """Ask on the console. End of input counts as pressing enter."""
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}\n> ").strip()
    except EOFError:
        answer = ""
    return answer or default


def show(path) -> None:
    """Open the file in its default viewer. Off Windows, the printed path is enough."""
    try:
        os.startfile(str(Path(path).resolve()))       # noqa: S606  (Windows)
    except (AttributeError, OSError):
        pass


def prompt_sent(work, name: str, rebuild) -> str:
    """The prompt file the pass wrote, or a rebuild of it if there is none yet.

    The file is what actually went, criticism from a retry included. Rebuilding it from the
    spec prints the prompt a fresh draw WOULD get, which after an `r1` is a different thing --
    and printing the wrong one is exactly the failure this whole block exists to stop.
    """
    path = Path(work) / name
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            pass
    return rebuild()


def sent(prompt: str, images) -> None:
    """The prompt in full, and the images that went with it, by path.

    Both halves matter and only one was ever printed. A render is the exterior plus a control
    image plus these words, and judging the result without seeing all three is guesswork --
    the same guesswork that had us reading numbers off draws for hours.
    """
    print("\n  ---- prompt sent ----")
    for line in (prompt or "").rstrip().splitlines():
        print(f"  | {line}")
    print("  ---- images sent ----")
    for label, path in images:
        if not path:
            print(f"  | {label:<10} -")
            continue
        mark = "" if Path(path).exists() else "   (not written yet)"
        print(f"  | {label:<10} {path}{mark}")
    print("  ---------------------")


def with_criticism(prompt: str, criticism: str = "", attach=(), first_index: int = 2) -> str:
    """The prompt, plus what was wrong with the last try and what the extra images are.

    Same construction as ``world_levels.job_builder._with_retry_context``: everything the
    first attempt was given is kept and the criticism goes on the end, because a retry that
    drops the original instructions trades one failure for another.

    `first_index` is what the first attachment is called, and it is not always 2. The plan
    pass sends one image, so an attachment is image 2; the render pass already sends the
    control plan as image 2 and says so in its own prompt, so an attachment there is image 3.
    Numbering them from 2 regardless would have the prompt call two different pictures "image
    2", which is worse than not numbering them at all.

    Non-ASCII is stripped rather than rejected: a smart quote pasted into the review prompt
    would otherwise fail the whole call in `openai_api.edit_image`, after the draw was paid
    for and while the person is looking at a menu.
    """
    criticism = (criticism or "").strip()
    if not criticism and not attach:
        return prompt
    lines = [prompt.rstrip(), ""]
    for position, path in enumerate(attach, start=first_index):
        lines.append(f"IMAGE {position} IS {Path(path).name}.")
    if criticism:
        lines.append(criticism)
    text = "\n".join(lines).rstrip() + "\n"
    return text.encode("ascii", "ignore").decode("ascii")


def split_retry(line: str) -> tuple[str, Path | None, str]:
    """Split `r <why> @<image> <note about it>` into (reason, image, note).

    The path is the one token straight after the `@`; everything after that token is the note
    describing it, with or without an `@@` in front. Taking the whole remainder as the filename
    is how a sentence ends up being stat()ed.
    """
    body = line[1:]
    body, _, tail = body.partition("@@")
    reason, _, token = body.partition("@")
    parts = token.split(None, 1)
    token = parts[0] if parts else ""
    note = " ".join(part.strip() for part in (parts[1] if len(parts) > 1 else "", tail)
                    if part.strip())
    if not token:
        # A note with nothing to attach it to is still criticism; keep it as the reason rather
        # than dropping it silently.
        return " ".join(part for part in (reason.strip(), note) if part), None, ""

    path = Path(token).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"no such image: {path}")
    # A stray non-ASCII character from a paste would make ascii_prompt reject the whole job.
    return reason.strip(), path, note.encode("ascii", "ignore").decode("ascii")
