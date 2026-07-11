"""Minimal Roboflow workflow debug — print raw API response shape."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from inference_sdk import InferenceHTTPClient

DEFAULT_IMAGE = (
    "levels/Frostreach/expanse/export/painted_4k_leonardo/chunk_06_06.png"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Debug Roboflow custom-workflow response.")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--workspace", default="douglass-workspace-y1brz")
    parser.add_argument("--workflow-id", default="custom-workflow")
    parser.add_argument("--input-name", default="image")
    parser.add_argument(
        "--out",
        default="levels/Frostreach/expanse/export/sam3_obstacle/chunk_06_06/debug_workflow_raw.json",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("ROBOFLOW_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ROBOFLOW_API_KEY is not set", file=sys.stderr)
        return 1

    repo = Path(__file__).resolve().parents[4]
    image_path = Path(args.image)
    if not image_path.is_absolute():
        image_path = (repo / image_path).resolve()
    if not image_path.exists():
        print(f"ERROR: missing image: {image_path}", file=sys.stderr)
        return 1

    print(f"image:     {image_path}")
    print(f"workspace: {args.workspace}")
    print(f"workflow:  {args.workflow_id}")
    print(f"input:     {args.input_name}")
    print("calling run_workflow …", flush=True)

    client = InferenceHTTPClient(
        api_url="https://serverless.roboflow.com",
        api_key=api_key,
    )
    result = client.run_workflow(
        workspace_name=args.workspace,
        workflow_id=args.workflow_id,
        images={args.input_name: str(image_path)},
        use_cache=False,
    )

    print(f"type:      {type(result).__name__}")
    if isinstance(result, list):
        print(f"list len:  {len(result)}")
        if result and isinstance(result[0], dict):
            print(f"keys[0]:   {list(result[0].keys())}")
    elif isinstance(result, dict):
        print(f"keys:      {list(result.keys())}")

    raw_json = json.dumps(result, indent=2, default=str)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (repo / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(raw_json + "\n", encoding="utf-8")
    print(f"saved:     {out_path}")
    print("--- response preview ---")
    print(raw_json[:8000])
    if len(raw_json) > 8000:
        print(f"... ({len(raw_json)} chars total, see saved file)")

    if isinstance(result, list) and result and isinstance(result[0], dict) and not result[0]:
        print("\nWARN: response is [{}] — workflow returned no named outputs to the API.", file=sys.stderr)
        print("      Check Roboflow workflow Outputs panel and wire viz/SAM3 to Workflow Output.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
