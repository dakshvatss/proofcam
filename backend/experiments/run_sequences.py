"""Multi-photo, order-independence experiment on the user's own setup (spec data/specs/my_setup.json).

ONE persistent InspectionAgent per inspection; photos are fed in several different orders. Perception of a
photo does not depend on inspection state, so each photo is perceived ONCE and the same observation is
replayed into every order: differences in the final assessment can then only come from the agent/policy.

    # Offline (free, no network): replay recorded observations (default: the committed fixture of the
    # 2026-10-31 live run). Next-view plans come from deterministic templates.
    python experiments/run_sequences.py
    python experiments/run_sequences.py --source ../runs/sequences-live-<ts>/perceptions.json

    # LIVE (costs money, ~$0.3-0.5): Muse+SAM perceive each needed photo once (from data/images/), then
    # every order is run with the live Muse planner. Saves perceptions.json for later free replays.
    python experiments/run_sequences.py --mode live [--group positive] [--variant label_only]

Groups (kept separate on purpose):
  positive - M2 router close-up, M3 switch close-up, M7 wide view; one unchanged installation, three orders.
  negative - M1 (switch port 3 empty), M5 (cable in switch port 4), M3 then M1 (two different physical
             configurations mixed without declaring a change), and M1 -> declared change -> M2, M3, M7.
Variants: label_only (spec as authored) and label_or_layout (same spec, port identity may use the declared
port_rows). Output: runs/sequences-<mode>-<ts>/<variant>/<sequence>/report.md + summary.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proofcam.agent import InspectionAgent  # noqa: E402
from proofcam.config import REPO_ROOT, Settings  # noqa: E402
from proofcam.evidence import ObservationRecord  # noqa: E402
from proofcam.images import ImageLoadError, NormalizedImage, load_image  # noqa: E402
from proofcam.meta_client import MetaClient  # noqa: E402
from proofcam.report import write_report  # noqa: E402
from proofcam.spec import InspectionSpec  # noqa: E402
from proofcam.trace import Trace  # noqa: E402

SPEC_PATH = REPO_ROOT / "data" / "specs" / "my_setup.json"
FIXTURE = REPO_ROOT / "backend" / "tests" / "fixtures" / "my_setup_live_observations.json"
IMAGES = {"m1": "m1_front.png", "m2": "m2_router_rear_close.png", "m3": "m3_switch_ports_close.png",
          "m4": "m4_wide_run.png", "m5": "m5_wrong_port.png", "m6": "m6_occluded.png",
          "m7": "m7_router_rear_far.png"}
CHANGE = "CHANGE"  # sentinel: technician declares the installation changed at this point
SEQUENCES = {
    "positive": {"A_m2-m3-m7": ["m2", "m3", "m7"],
                 "B_m3-m7-m2": ["m3", "m7", "m2"],
                 "C_m7-m2-m3": ["m7", "m2", "m3"]},
    "negative": {"N1_m1-empty-port": ["m1"],
                 "N2_m5-wrong-port": ["m5"],
                 "N3_m3-m1-undeclared-change": ["m3", "m1"],
                 "N4_m1-CHANGE-m2-m3-m7": ["m1", CHANGE, "m2", "m3", "m7"]},
}


def variant_spec(base: InspectionSpec, variant: str) -> InspectionSpec:
    d = json.loads(base.model_dump_json())
    for r in d["requirements"]:
        r["port_identity"] = variant
    return InspectionSpec.model_validate(d)


def load_records(path: Path) -> dict[str, ObservationRecord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: ObservationRecord.model_validate({"seq": 0, **v}) for k, v in data["observations"].items()}


def local_image(key: str, settings: Settings, expect_id: str | None = None) -> NormalizedImage | None:
    try:
        img = load_image(REPO_ROOT / "data" / "images" / IMAGES[key], settings.image_max_side)
    except (ImageLoadError, FileNotFoundError):
        return None
    return img if expect_id is None or img.image_id == expect_id else None


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"offline replay attempted a network call: {request.url}")


async def perceive_live(settings: Settings, spec: InspectionSpec, keys: list[str], out: Path):
    """One live Muse+SAM perception per photo; saved in the fixture format."""
    trace = Trace()
    client = MetaClient(settings, trace)
    agent = InspectionAgent(spec, client, settings)
    recs, runs, imgs = {}, {}, {}
    try:
        for k in keys:
            img = local_image(k, settings)
            if img is None:
                raise SystemExit(f"missing photo data/images/{IMAGES[k]}")
            print(f"perceiving {k} ({img.image_id}) ...", flush=True)
            rec, run, notes, _ = await agent._perceive(img, seq=0)
            recs[k], runs[k], imgs[k] = rec, run, img
            for n in notes:
                print("  note:", n)
    finally:
        await client.aclose()
    (out / "perceptions.json").write_text(json.dumps({
        "_provenance": f"LIVE Muse+SAM perception, {time.strftime('%Y-%m-%d %H:%M')}, spec {SPEC_PATH.name}",
        "observations": {k: r.model_dump(exclude={"seq", "responding_to", "epoch"}) for k, r in recs.items()},
    }, indent=1), encoding="utf-8")
    trace.write_jsonl(out / "perception_trace.jsonl")
    return recs, runs, imgs, trace.summary()


def fingerprint(agent: InspectionAgent) -> dict:
    """Order-free description of the final assessment (photos named by file, not by sequence number)."""
    name = {o.seq: o.source_name for o in agent.observations}
    out = []
    for a in agent.assessments:
        out.append({
            "status": a.status, "identity_state": a.identity_state,
            "endpoints": [{"endpoint": f"{ep.device_id} {ep.port_label}", "state": ep.state,
                           "support": sorted({f"{name[s.seq]}:{s.port_basis}" for s in ep.support}),
                           "conflicts": sorted({name[c.seq] for c in ep.conflicts})} for ep in a.endpoints],
            "identity_evidence": sorted({name[x.seq] for x in a.identity_evidence}),
            "gaps": sorted(g.key for g in a.gaps),
        })
    return {"requirements": out}


async def run_sequence(settings: Settings, spec: InspectionSpec, order: list[str], recs, runs, imgs, live: bool,
                       out_dir: Path) -> dict:
    trace = Trace()
    client = (MetaClient(settings, trace) if live
              else MetaClient(settings, trace, transport=httpx.MockTransport(_no_network), source="replay"))
    agent = InspectionAgent(spec, client, settings, plan_with_muse=live)
    steps = []
    try:
        for k in order:
            if k == CHANGE:
                agent.mark_installation_changed("technician declared the installation changed (scripted)")
                steps.append({"event": "installation_changed"})
                continue
            if agent.done:
                steps.append({"photo": k, "skipped": f"inspection already stopped: {agent.stop_reason}"})
                continue
            st = await agent.observe_recorded(recs[k], imgs.get(k), runs.get(k))
            steps.append({"photo": k, "statuses": [a.status for a in st.assessments],
                          "gaps": [g.key for a in st.assessments for g in a.gaps],
                          "next_view": st.next_view.model_dump(include={"id", "gap_code", "planner", "instruction"})
                          if st.next_view else None, "stop_reason": st.stop_reason, "notes": st.notes})
    finally:
        await client.aclose()
    write_report(agent, out_dir)
    return {"order": order, "steps": steps, "final": fingerprint(agent), "stop_reason": agent.stop_reason,
            "explanations": [a.explanation for a in agent.assessments],
            "assumptions": [x for a in agent.assessments for x in a.assumptions],
            "usage": trace.summary(), "report": str(out_dir / "report.md")}


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["replay", "live"], default="replay")
    ap.add_argument("--source", type=Path, default=FIXTURE, help="recorded observations (replay mode)")
    ap.add_argument("--group", choices=list(SEQUENCES), action="append")
    ap.add_argument("--variant", choices=["label_only", "label_or_layout"], action="append")
    a = ap.parse_args()
    groups = a.group or list(SEQUENCES)
    variants = a.variant or ["label_only", "label_or_layout"]
    live = a.mode == "live"
    settings = Settings.from_env() if live else Settings(api_key="offline-replay")
    base = InspectionSpec.load(SPEC_PATH)
    out = REPO_ROOT / "runs" / f"sequences-{a.mode}-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)

    needed = sorted({k for g in groups for seq in SEQUENCES[g].values() for k in seq if k != CHANGE})
    if live:
        recs, runs, imgs, perception_usage = await perceive_live(settings, base, needed, out)
        source = "live perception (once per photo) + live Muse planner"
    else:
        recs = load_records(a.source)
        runs = {}
        imgs = {k: img for k in needed if (img := local_image(k, settings, recs[k].image_id))}
        perception_usage = None
        source = f"replay of {a.source} + deterministic planner (no API calls)"

    results: dict = {"mode": a.mode, "source": source, "perception_usage": perception_usage, "runs": {}}
    for variant in variants:
        spec = variant_spec(base, variant)
        for g in groups:
            for name, order in SEQUENCES[g].items():
                print(f"--- [{variant}] {g} {name}", flush=True)
                r = await run_sequence(settings, spec, order, recs, runs, imgs, live, out / variant / name)
                results["runs"].setdefault(variant, {})[name] = {"group": g, **r}
                for st in r["steps"]:
                    nv = (st.get("next_view") or {}).get("instruction", "")
                    print(f"  {st.get('photo', st.get('event'))}: {st.get('statuses', '')} "
                          f"{st.get('stop_reason') or ''} {('-> ' + nv[:140]) if nv else ''}")
        pos = [results["runs"][variant][n]["final"] for n in SEQUENCES["positive"]] if "positive" in groups else []
        if pos:
            same = all(p == pos[0] for p in pos)
            results.setdefault("order_independent", {})[variant] = same
            print(f"[{variant}] positive orders reach identical final assessment: {same}")
    (out / "summary.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    asyncio.run(main())
