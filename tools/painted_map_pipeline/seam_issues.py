from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from .assemble_preview import assemble_preview, load_manifest, save_preview_image
from .make_seam_contexts import _affected_chunks, _repair_goal_for_feature, make_patch_from_issue

Image.MAX_IMAGE_PIXELS = None

ISSUE_STATUSES = (
    "open",
    "context_ready",
    "fix_generated",
    "applied",
    "accepted",
    "rejected",
    "needs_retry",
)

ISSUE_PRIORITIES = ("low", "medium", "high")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _issues_path(pass_dir: Path):
    return pass_dir / "issues.json"


def _load_registry(pass_dir: Path):
    pass_dir = Path(pass_dir)
    path = _issues_path(pass_dir)
    if not path.exists():
        raise FileNotFoundError(f"Issue registry not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_registry(pass_dir: Path, registry: dict):
    pass_dir = Path(pass_dir)
    pass_dir.mkdir(parents=True, exist_ok=True)
    _issues_path(pass_dir).write_text(json.dumps(registry, indent=2), encoding="utf-8")


def _parse_rect(raw: str):
    parts = [int(v.strip()) for v in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("Rect must be x,y,width,height")
    return parts


def _parse_connections(raw: str | None):
    if not raw:
        return []
    return [item.strip() for item in raw.replace("|", ";").split(";") if item.strip()]


def _find_issue(registry: dict, issue_id: str):
    for issue in registry.get("issues", []):
        if issue["issue_id"] == issue_id:
            return issue
    raise KeyError(f"Issue not found: {issue_id}")


def _next_patch_attempt_id(issue: dict):
    attempts = issue.get("patch_attempts", [])
    return f"{issue['issue_id']}_attempt_{len(attempts) + 1:02d}"


def _write_pass_summary(pass_dir: Path, registry: dict):
    groups = {status: [] for status in ISSUE_STATUSES}
    for issue in registry.get("issues", []):
        status = issue.get("status", "open")
        groups.setdefault(status, []).append(issue["issue_id"])

    lines = [
        "# Seam Pass Summary",
        "",
        f"Pass: `{pass_dir}`",
        f"Manifest: `{registry.get('manifest', '')}`",
        f"Issue count: {len(registry.get('issues', []))}",
        "",
    ]
    section_titles = {
        "open": "Open Issues",
        "context_ready": "Context Ready",
        "fix_generated": "Fix Generated",
        "applied": "Applied",
        "accepted": "Accepted Fixes",
        "rejected": "Rejected Fixes",
        "needs_retry": "Needs Retry",
    }
    for status, title in section_titles.items():
        ids = groups.get(status, [])
        lines.append(f"## {title}")
        if ids:
            lines.extend(f"- {issue_id}" for issue_id in ids)
        else:
            lines.append("- none")
        lines.append("")

    (pass_dir / "pass_summary.md").write_text("\n".join(lines), encoding="utf-8")


def render_issue_review(pass_dir, *, max_width=1800):
    pass_dir = Path(pass_dir)
    registry = _load_registry(pass_dir)
    manifest_path = registry["manifest"]
    _, manifest = load_manifest(manifest_path)

    preview_path = pass_dir / "assembled_before.png"
    if not preview_path.exists():
        assemble_preview(
            manifest_path,
            preview_path,
            max_width=max_width,
            draw_grid=True,
            draw_labels=True,
        )

    with Image.open(preview_path) as preview:
        preview = preview.convert("RGBA")
        scale = preview.width / int(manifest["image_size"][0])
        canvas = preview.copy()
        draw = ImageDraw.Draw(canvas)

        for issue in registry.get("issues", []):
            x, y, w, h = [int(v) for v in issue["global_rect"]]
            left = int(round(x * scale))
            top = int(round(y * scale))
            right = int(round((x + w) * scale)) - 1
            bottom = int(round((y + h) * scale)) - 1
            draw.rectangle((left, top, right, bottom), outline=(255, 0, 0, 255), width=3)
            label = issue["issue_id"]
            draw.rectangle((left, top, left + 8 + 8 * len(label), top + 22), fill=(255, 0, 0, 200))
            draw.text((left + 4, top + 4), label, fill=(255, 255, 255, 255))

        output_path = pass_dir / "issue_review.png"
        canvas.save(output_path)
        return {"issue_review": str(output_path), "issue_count": len(registry.get("issues", []))}


def init_issue_pass(manifest_path, pass_dir, *, max_width=1800):
    manifest_path, manifest = load_manifest(manifest_path)
    pass_dir = Path(pass_dir)
    pass_dir.mkdir(parents=True, exist_ok=True)

    assemble_preview(
        manifest_path,
        pass_dir / "assembled_before.png",
        max_width=max_width,
        draw_grid=True,
        draw_labels=True,
    )

    registry = {
        "manifest": str(manifest_path),
        "pass_dir": str(pass_dir),
        "created_at": _now_iso(),
        "issues": [],
    }
    _save_registry(pass_dir, registry)
    render_issue_review(pass_dir, max_width=max_width)
    _write_pass_summary(pass_dir, registry)
    return registry


def add_issue(
    pass_dir,
    *,
    issue_id,
    feature_type,
    global_rect,
    problem,
    expected_fix,
    boundary="",
    connections=None,
    affected_chunks=None,
    priority="medium",
    created_by="user",
    review_notes="",
    repair_goal=None,
    status="open",
):
    pass_dir = Path(pass_dir)
    registry = _load_registry(pass_dir)
    if any(item["issue_id"] == issue_id for item in registry.get("issues", [])):
        raise ValueError(f"Issue already exists: {issue_id}")

    manifest_path, manifest = load_manifest(registry["manifest"])
    rect = [int(v) for v in global_rect]
    if not affected_chunks:
        affected_chunks = [item["chunk_id"] for item in _affected_chunks(manifest, rect)]

    issue = {
        "issue_id": issue_id,
        "status": status,
        "priority": priority,
        "feature_type": feature_type,
        "boundary": boundary,
        "affected_chunks": affected_chunks,
        "global_rect": rect,
        "connections": connections or [],
        "repair_goal": repair_goal or _repair_goal_for_feature(feature_type),
        "problem": problem,
        "expected_fix": expected_fix,
        "created_by": created_by,
        "review_notes": review_notes,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "patch_attempts": [],
    }
    registry.setdefault("issues", []).append(issue)
    _save_registry(pass_dir, registry)
    render_issue_review(pass_dir)
    _write_pass_summary(pass_dir, registry)
    return issue


def make_issue_patch(pass_dir, issue_id, *, max_context_width=1800):
    pass_dir = Path(pass_dir)
    registry = _load_registry(pass_dir)
    issue = _find_issue(registry, issue_id)
    patch_id = _next_patch_attempt_id(issue)
    patch_issue = dict(issue)
    patch_issue["patch_id"] = patch_id

    metadata = make_patch_from_issue(
        registry["manifest"],
        pass_dir,
        patch_issue,
        max_context_width=max_context_width,
    )
    attempt = {
        "patch_id": patch_id,
        "patch_dir": str(pass_dir / "patches" / patch_id),
        "created_at": _now_iso(),
        "metadata": metadata,
    }
    issue.setdefault("patch_attempts", []).append(attempt)
    issue["status"] = "context_ready"
    issue["updated_at"] = _now_iso()
    _save_registry(pass_dir, registry)
    _write_pass_summary(pass_dir, registry)
    return {"issue_id": issue_id, "patch_id": patch_id, "patch_dir": attempt["patch_dir"]}


def update_issue_status(pass_dir, issue_id, status, *, review_notes=None):
    if status not in ISSUE_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    pass_dir = Path(pass_dir)
    registry = _load_registry(pass_dir)
    issue = _find_issue(registry, issue_id)
    issue["status"] = status
    issue["updated_at"] = _now_iso()
    if review_notes is not None:
        issue["review_notes"] = review_notes
    _save_registry(pass_dir, registry)
    _write_pass_summary(pass_dir, registry)
    return issue


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage seam issue inventory for a repair pass.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a seam issue pass.")
    init_parser.add_argument("--manifest", required=True)
    init_parser.add_argument("--pass-dir", required=True)
    init_parser.add_argument("--max-width", type=int, default=1800)

    add_parser = subparsers.add_parser("add", help="Add an issue to the pass registry.")
    add_parser.add_argument("--pass-dir", required=True)
    add_parser.add_argument("--issue-id", required=True)
    add_parser.add_argument("--feature-type", required=True)
    add_parser.add_argument("--priority", choices=ISSUE_PRIORITIES, default="medium")
    add_parser.add_argument("--boundary", default="")
    add_parser.add_argument("--rect", required=True, help="Global rect as x,y,width,height")
    add_parser.add_argument("--connections", default="")
    add_parser.add_argument("--affected-chunks", default="", help="Comma-separated chunk ids")
    add_parser.add_argument("--problem", required=True)
    add_parser.add_argument("--expected-fix", required=True)
    add_parser.add_argument("--created-by", default="user")
    add_parser.add_argument("--review-notes", default="")
    add_parser.add_argument("--repair-goal", default="")

    review_parser = subparsers.add_parser("render-review", help="Render annotated issue review image.")
    review_parser.add_argument("--pass-dir", required=True)
    review_parser.add_argument("--max-width", type=int, default=1800)

    patch_parser = subparsers.add_parser("make-patch", help="Create patch context for one issue.")
    patch_parser.add_argument("--pass-dir", required=True)
    patch_parser.add_argument("--issue-id", required=True)
    patch_parser.add_argument("--max-context-width", type=int, default=1800)

    status_parser = subparsers.add_parser("status", help="Update issue status.")
    status_parser.add_argument("--pass-dir", required=True)
    status_parser.add_argument("--issue-id", required=True)
    status_parser.add_argument("--status", required=True, choices=ISSUE_STATUSES)
    status_parser.add_argument("--review-notes", default="")

    args = parser.parse_args(argv)

    if args.command == "init":
        result = init_issue_pass(args.manifest, args.pass_dir, max_width=args.max_width)
    elif args.command == "add":
        affected = (
            [item.strip() for item in args.affected_chunks.split(",") if item.strip()]
            if args.affected_chunks
            else None
        )
        result = add_issue(
            args.pass_dir,
            issue_id=args.issue_id,
            feature_type=args.feature_type,
            global_rect=_parse_rect(args.rect),
            problem=args.problem,
            expected_fix=args.expected_fix,
            boundary=args.boundary,
            connections=_parse_connections(args.connections),
            affected_chunks=affected,
            priority=args.priority,
            created_by=args.created_by,
            review_notes=args.review_notes,
            repair_goal=args.repair_goal or None,
        )
    elif args.command == "render-review":
        result = render_issue_review(args.pass_dir, max_width=args.max_width)
    elif args.command == "make-patch":
        result = make_issue_patch(args.pass_dir, args.issue_id, max_context_width=args.max_context_width)
    elif args.command == "status":
        notes = args.review_notes or None
        result = update_issue_status(args.pass_dir, args.issue_id, args.status, review_notes=notes)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
