"""ProofCam CLI: run a real (live Meta API) inspection over saved photographs.

  python -m proofcam.cli --spec ../data/specs/router_switch.json --image a.jpg [--image b.jpg ...]
  python -m proofcam.cli --spec ... --image a.jpg --interactive   # prompts for each follow-up photo path

Photos may be supplied in any order: one persistent agent accumulates the evidence, and each photo is
recorded as answering the most recent next-view request. Static verification is assumed (all photos show
one unchanged installation; a clear violation ends the inspection). In --interactive mode, type
  !changed <reason>
after physically changing the installation: earlier photos then stop counting as evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

from .agent import InspectionAgent, StepResult
from .config import REPO_ROOT, MissingCredentialsError, Settings
from .images import ImageLoadError, load_image
from .meta_client import MetaClient
from .report import write_report
from .spec import InspectionSpec
from .trace import Trace


def _print_step(step: StepResult) -> None:
    print(f"\n=== Photo {step.seq} ({step.image_id}) ===")
    for a in step.assessments:
        print(f"  {a.requirement_id}: {a.status}")
        print(f"    {a.explanation}")
    for n in step.notes:
        print(f"  note: {n}")
    if step.next_view:
        nv = step.next_view
        print(f"\n  NEXT VIEW [{nv.id}] ({nv.planner}, gap {nv.gap_code}):\n    {nv.instruction}")
        print(f"    missing: {nv.missing_fact}\n    resolves if: {nv.success_criteria}")
    if step.stop_reason:
        print(f"\n  STOP: {step.stop_reason}")


async def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    spec = InspectionSpec.load(args.spec)
    paths = list(args.image)
    trace = Trace()
    client = MetaClient(settings, trace)
    agent = InspectionAgent(spec, client, settings, require_grounding=not args.no_grounding_requirement)
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_dir = Path(args.out) / run_id
    try:
        i = 0
        while True:
            if i < len(paths) and not agent.done:
                path = paths[i]
                i += 1
            elif args.interactive:
                path = input("\nPath to next photo (blank to stop; '!changed <reason>' after a physical change): "
                             ).strip().strip('"')
                if not path:
                    break
                if path.startswith("!changed"):
                    try:
                        agent.mark_installation_changed(path[len("!changed"):].strip() or "declared by user")
                        print("  installation change recorded; earlier photos no longer count as evidence")
                    except RuntimeError as e:
                        print(f"  cannot reopen: {e}")
                    continue
                if agent.done:
                    print(f"  inspection stopped ({agent.stop_reason}); declare a change with !changed to continue")
                    continue
            else:
                break
            try:
                img = load_image(path, settings.image_max_side)
            except ImageLoadError as e:
                print(f"  skipped: {e}")
                continue
            _print_step(await agent.observe(img))
        if not agent.done:
            print("\n(no more photos supplied; inspection left open — findings reflect evidence so far)")
    finally:
        await client.aclose()
        if agent.observations:
            write_report(agent, run_dir)
            s = trace.summary()
            print(f"\nReport: {run_dir / 'report.md'}\nModel calls: {s['model_calls']} · "
                  f"est. cost ${s['estimated_cost_usd']:.4f}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="proofcam", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--image", action="append", default=[], help="photo path; repeat for follow-ups")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--out", default=str(REPO_ROOT / "runs"))
    ap.add_argument("--no-grounding-requirement", action="store_true",
                    help="do not require SAM corroboration for endpoint support (ablation only)")
    args = ap.parse_args()
    if not args.image and not args.interactive:
        ap.error("supply at least one --image, or --interactive")
    try:
        sys.exit(asyncio.run(run(args)))
    except MissingCredentialsError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
