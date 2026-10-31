"""Order-independent evidence accumulation with ONE persistent agent per inspection (no network).

Uses tests/fixtures/my_setup_live_observations.json: Muse/SAM output RECORDED from a live run on the user's
own router+switch photos (2026-10-31), replayed offline via InspectionAgent.observe_recorded (trace
source='replay'). Planning uses deterministic templates, so no API call can happen.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from pathlib import Path

import httpx
import pytest

from fakes import settings
from proofcam.agent import InspectionAgent
from proofcam.evidence import ObservationRecord
from proofcam.meta_client import MetaClient
from proofcam.report import write_report
from proofcam.spec import InspectionSpec
from proofcam.trace import Trace

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "my_setup_live_observations.json").read_text("utf-8"))
RECS = {k: ObservationRecord.model_validate({"seq": 0, **v}) for k, v in FIXTURE["observations"].items()}
POSITIVE = ["m2", "m3", "m7"]  # router close-up, switch close-up, wide view: one unchanged installation


def spec(variant: str = "label_only") -> InspectionSpec:
    d = json.loads((ROOT / "data" / "specs" / "my_setup.json").read_text("utf-8"))
    d["requirements"][0]["port_identity"] = variant
    return InspectionSpec.model_validate(d)


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"network call during replay: {request.url}")


def new_agent(variant="label_only", **budget) -> InspectionAgent:
    s = settings(**budget)
    client = MetaClient(s, Trace(), transport=httpx.MockTransport(_no_network), source="replay")
    return InspectionAgent(spec(variant), client, s, plan_with_muse=False)


def feed(agent: InspectionAgent, keys):
    return [asyncio.run(agent.observe_recorded(RECS[k])) for k in keys]


def fingerprint(agent: InspectionAgent):
    name = {o.seq: o.source_name for o in agent.observations}
    return [(a.status, a.identity_state, sorted(g.key for g in a.gaps),
             [(ep.state, sorted(f"{name[s.seq]}:{s.port_basis}" for s in ep.support),
               sorted(name[c.seq] for c in ep.conflicts)) for ep in a.endpoints],
             sorted(name[x.seq] for x in a.identity_evidence)) for a in agent.assessments]


# --------------------------------------------------------------------------- positive, unchanged installation

@pytest.mark.parametrize("variant", ["label_only", "label_or_layout"])
def test_recorded_positive_set_is_order_independent(variant):
    finals = []
    for order in itertools.permutations(POSITIVE):
        ag = new_agent(variant)
        steps = feed(ag, order)
        assert not ag.done, "the agent must not stop before all photos are in"
        assert len(ag.observations) == 3 and [o.seq for o in ag.observations] == [1, 2, 3]
        assert all(s.next_view is not None for s in steps)
        finals.append(fingerprint(ag))
    assert all(f == finals[0] for f in finals)
    # These photos have hidden / partly readable target labels: combining them must NOT verify.
    assert finals[0][0][0] == "INSUFFICIENT_EVIDENCE"


def test_recorded_positive_strict_labels_establish_nothing():
    ag = new_agent("label_only")
    feed(ag, POSITIVE)
    a = ag.assessments[0]
    assert [ep.state for ep in a.endpoints] == ["unknown", "unknown"]
    # The plug-in-hidden-label evidence is kept and explains the gap instead of "port not found".
    assert {ep.gap.code for ep in a.endpoints} == {"LABEL_ILLEGIBLE"}
    assert all(ep.gap.context.get("label_hidden_by_plug") for ep in a.endpoints)
    assert all(ep.gap.context.get("layout_inference_available") for ep in a.endpoints)


def test_recorded_positive_layout_variant_accumulates_complementary_endpoints():
    ag = new_agent("label_or_layout")
    feed(ag, ["m7", "m3", "m2"])
    a = ag.assessments[0]
    names = {o.seq: o.source_name for o in ag.observations}
    router, switch = a.endpoints
    assert router.state == switch.state == "established"
    assert {names[s.seq] for s in router.support} == {"m2_router_rear_close.png"}
    assert {names[s.seq] for s in switch.support} == {"m3_switch_ports_close.png"}
    assert all(s.port_basis == "layout_inference" for s in router.support + switch.support)
    # m7 traces the cable but its port labels are only partially legible: identity is NOT established.
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"
    g = next(g for g in a.gaps if g.code == "CABLE_CONTINUITY")
    assert "m7" not in g.missing_fact and g.context["near_misses"]
    assert len(a.assumptions) == 2


def test_guidance_targets_device_in_view_and_skips_established_endpoints():
    ag = new_agent("label_only")
    s1 = feed(ag, ["m2"])[0]  # router rear close-up; switch absent
    assert s1.next_view.gap_code == "LABEL_ILLEGIBLE" and "Router" in s1.next_view.instruction
    ag = new_agent("label_or_layout")
    s1, s2 = feed(ag, ["m2", "m3"])
    assert s1.next_view.target_region.startswith("Switch")  # router already established
    assert s2.next_view.gap_code == "CABLE_CONTINUITY"


def test_repeated_gap_guidance_changes_and_is_bounded():
    ag = new_agent("label_or_layout", max_attempts_per_gap=2)
    s = feed(ag, ["m2", "m3", "m7"])
    assert s[1].next_view.gap_code == s[2].next_view.gap_code == "CABLE_CONTINUITY"
    assert "did not resolve" in s[2].next_view.instruction  # does not repeat the identical instruction
    assert ag.gap_attempts["R1:CABLE_CONTINUITY:None"] == 2


# --------------------------------------------------------------------------- negative cases (kept separate)

@pytest.mark.parametrize("key", ["m1", "m5"])
def test_recorded_clear_empty_target_port_is_violated_and_stops(key):
    ag = new_agent()
    s = feed(ag, [key])[0]
    assert s.assessments[0].status == "VIOLATED" and s.stop_reason == "all_requirements_resolved"
    assert "port is empty" in s.assessments[0].explanation
    with pytest.raises(RuntimeError):
        feed(ag, ["m2"])  # static verification: a violation is terminal unless a change is declared


def test_undeclared_configuration_mix_is_a_contradiction_not_a_verification():
    ag = new_agent("label_or_layout")
    feed(ag, ["m3", "m1"])  # m3: plug in switch port 3; m1: switch port 3 empty (different configuration)
    a = ag.assessments[0]
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[1].state == "contradicted"
    g = a.endpoints[1].gap
    assert g.code == "CONTRADICTION" and "declared" in g.missing_fact
    assert ag.requests[-1].gap_code == "CONTRADICTION"  # contradictions are requested first


def test_declared_installation_change_supersedes_old_photos():
    ag = new_agent("label_or_layout")
    assert feed(ag, ["m1"])[0].assessments[0].status == "VIOLATED"
    ag.mark_installation_changed("cable plugged into switch port 3")
    assert not ag.done and ag.epoch == 1
    feed(ag, POSITIVE)
    ref = new_agent("label_or_layout")
    feed(ref, POSITIVE)
    a = ag.assessments[0]
    assert a.endpoints[1].state == "established" and not a.endpoints[1].conflicts  # m1 no longer counts
    assert [x[:3] for x in fingerprint(ag)] == [x[:3] for x in fingerprint(ref)]
    assert ag.history[1]["event"] == "installation_changed" and ag.history[1]["superseded_photos"] == [1]


def test_change_cannot_reopen_a_budget_stop():
    ag = new_agent(max_observations=1)
    feed(ag, ["m2"])
    assert ag.stop_reason == "observation_budget_exhausted"
    with pytest.raises(RuntimeError):
        ag.mark_installation_changed("x")


# --------------------------------------------------------------------------- duplicates, unusable, budget

def test_duplicate_photo_adds_nothing_and_costs_nothing():
    ag = new_agent()
    s1 = feed(ag, ["m2"])[0]
    s2 = feed(ag, ["m2"])[0]
    assert len(ag.observations) == 1 and s2.seq == 1
    assert "Duplicate" in s2.notes[0] and s2.next_view == s1.next_view
    assert ag.gap_attempts == {s1.next_view.gap_key: 1}
    assert ag.trace.model_calls() == []


def test_unusable_photo_contributes_nothing():
    junk = RECS["m2"].model_copy(deep=True, update={"image_id": "img_junk", "source_name": "blurry.jpg"})
    junk.extraction.image_usable = False
    junk.extraction.image_issues = ["motion blur"]
    ag = new_agent()
    feed(ag, ["m3"])
    before = fingerprint(ag)
    s = asyncio.run(ag.observe_recorded(junk))
    assert fingerprint(ag) == before and "motion blur" in s.notes[0]


def test_image_budget_exhaustion_stops_with_insufficient_evidence():
    ag = new_agent("label_or_layout", max_observations=2)
    s = feed(ag, ["m2", "m3"])
    assert s[-1].stop_reason == "observation_budget_exhausted"
    assert s[-1].assessments[0].status == "INSUFFICIENT_EVIDENCE"


# --------------------------------------------------------------------------- report

def test_multi_photo_report_shows_order_timeline_and_provenance(tmp_path):
    ag = new_agent("label_or_layout")
    feed(ag, ["m3", "m7", "m2"])
    r = write_report(ag, tmp_path / "run")
    md = (tmp_path / "run" / "report.md").read_text("utf-8")
    assert [p["source_name"] for p in r["photo_order"]] == ["m3_switch_ports_close.png",
                                                            "m7_router_rear_far.png", "m2_router_rear_close.png"]
    assert len(r["history"]) == 3 and all("requirements" in h for h in r["history"])
    for needle in ("## Timeline", "## Final verdict", "Contributes to the final assessment",
                   "layout_inference", "Assumption:", "Near miss", "est. cost"):
        assert needle in md, needle
    assert {e["source"] for e in (json.loads(x) for x in
                                  (tmp_path / "run" / "trace.jsonl").read_text("utf-8").splitlines())
            if e["name"] == "observe_recorded"} == {"replay"}
