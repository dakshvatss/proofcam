"""Three devices, two independent connection requirements (Ethernet + HDMI) in ONE inspection.

Mocked model claims only (no network, NOT real inference). The spec is a synthetic test fixture
(tests/fixtures/three_device_spec.json); its labels and colours are test inputs, not facts about real hardware.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from fakes import FakeMeta, cable, device, extraction, make_image, plan, port, sam_record, settings
from proofcam.agent import InspectionAgent
from proofcam.api import create_app
from proofcam.evidence import GroundingLink, ObservationRecord
from proofcam.observation import ObservationExtraction
from proofcam.policy import (assess_requirement, connector_match, mixed_connector_devices, overall_assessment,
                             select_gap)
from proofcam.report import render_markdown
from proofcam.service import InspectionService, ServiceConfig
from proofcam.spec import InspectionSpec
from proofcam.store import Store
from test_api import err, upload

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "three_device_spec.json"
ETH, HDMI = "blue ethernet cable", "black hdmi cable"
OBS, PLAN = "ObservationExtraction", "NextViewPlan"


@pytest.fixture
def spec() -> InspectionSpec:
    return InspectionSpec.load(FIXTURE)


def variant(spec: InspectionSpec, req_id: str, **changes) -> InspectionSpec:
    d = json.loads(spec.model_dump_json())
    for r in d["requirements"]:
        if r["id"] == req_id:
            r.update(changes)
    return InspectionSpec.model_validate(d)


def cport(ref, dev, label, conn, **kw):
    d = port(ref, dev, label, **kw)
    d["connector_type"] = conn
    return d


def ccable(ref, color, ports, conn, path="fully_traced"):
    d = cable(ref, color, ports, path=path)
    d["connector_type"] = conn
    return d


def rec(seq, ext: dict, grounded: dict[str, str] | None = None, epoch: int = 0) -> ObservationRecord:
    """grounded: port ref -> SAM concept whose mask reaches that port."""
    links = {f"{p}|{c}": GroundingLink(concept=c, sam_object_id="0", overlap_px=500, corroborated=True, note="test")
             for p, c in (grounded or {}).items()}
    return ObservationRecord(seq=seq, image_id=f"img_{seq}", source_name=f"{seq}.jpg", width=400, height=300,
                             epoch=epoch, extraction=ObservationExtraction.model_validate(ext), port_links=links)


def assess(spec, obs):
    return [assess_requirement(spec, r, obs) for r in spec.requirements]


# Photo of the network run: router LAN 2 -> console LAN, blue Ethernet cable traced end to end.
ETH_PHOTO = extraction(
    devices=[device("D1", "router"), device("D2", "ps5")],
    ports=[cport("P1", "D1", "2", "ethernet", group="LAN", color="blue"),
           cport("P2", "D2", "LAN", "ethernet", color="blue", box=(600, 400, 660, 480))],
    cables=[ccable("C1", "blue", ["P1", "P2"], "ethernet")])
ETH_GROUNDED = {"P1": ETH, "P2": ETH}


def hdmi_photo(tv_occ="cable_inserted", tv_color="black", tv_label="HDMI 2", console_label="HDMI OUT",
               legible="legible"):
    return extraction(
        devices=[device("D1", "ps5"), device("D2", "tv")],
        ports=[cport("P1", "D1", console_label, "hdmi", color="black", legible=legible),
               cport("P2", "D2", tv_label, "hdmi", occ=tv_occ, color=tv_color if tv_occ == "cable_inserted" else None,
                     box=(600, 400, 660, 480))],
        cables=[ccable("C1", "black", ["P1", "P2"] if tv_occ == "cable_inserted" else ["P1"], "hdmi")])


HDMI_GROUNDED = {"P1": HDMI, "P2": HDMI}


# ------------------------------------------------------------------------------------------------ 1. loading

def test_three_devices_and_two_requirements_load(spec):
    assert [d.id for d in spec.devices] == ["router", "ps5", "tv"]
    assert [(r.id, r.connector, r.cable_concept()) for r in spec.requirements] == [("R1", "ethernet", ETH),
                                                                                  ("R2", "hdmi", HDMI)]
    assert mixed_connector_devices(spec) == {"ps5"}  # the console carries both connector families


def test_existing_specs_default_to_ethernet_and_have_no_mixed_devices():
    for name in ("router_switch", "my_setup"):
        s = InspectionSpec.load(ROOT / "data" / "specs" / f"{name}.json")
        assert {r.connector for r in s.requirements} == {"ethernet"} and mixed_connector_devices(s) == set()


def test_draft_template_with_todo_placeholders_cannot_be_loaded():
    with pytest.raises(ValueError, match="TODO"):
        InspectionSpec.load(ROOT / "data" / "specs" / "drafts" / "ps5_home_setup.json")


def test_only_loadable_specs_are_listed(tmp_path, spec):
    (tmp_path / "three.json").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "draft.json").write_text(
        (ROOT / "data" / "specs" / "drafts" / "ps5_home_setup.json").read_text(encoding="utf-8"), encoding="utf-8")
    svc = InspectionService(settings(), Store(tmp_path / "x.db"), config=ServiceConfig(specs_dir=tmp_path))
    listed = svc.list_specs()
    assert [s.spec_id for s in listed] == ["three"]
    assert listed[0].devices == ["Test Router", "Test Console", "Test TV"]
    assert [r.connector for r in listed[0].requirements] == ["ethernet", "hdmi"]


def test_observations_recorded_before_connector_types_still_load():
    o = ObservationExtraction.model_validate(extraction(ports=[port("P1", "D1", "1")], cables=[cable("C1", "blue", ["P1"])],
                                                        devices=[device("D1", "router")]))
    assert o.ports[0].connector_type == "unclear" and o.cables[0].connector_type == "unclear"
    assert connector_match("unclear", "ethernet") == "unknown" and connector_match("other", "hdmi") == "mismatch"


# ------------------------------------------------------------------------------------- 2-4. overall verdict

def test_r1_verified_r2_unresolved_is_overall_insufficient(spec):
    a = assess(spec, [rec(1, ETH_PHOTO, ETH_GROUNDED)])
    assert [x.status for x in a] == ["VERIFIED", "INSUFFICIENT_EVIDENCE"]
    o = overall_assessment(a)
    assert o.status == "INSUFFICIENT_EVIDENCE" and o.requirement_statuses == {"R1": "VERIFIED",
                                                                              "R2": "INSUFFICIENT_EVIDENCE"}


def test_both_verified_with_valid_evidence_is_overall_verified(spec):
    a = assess(spec, [rec(1, ETH_PHOTO, ETH_GROUNDED), rec(2, hdmi_photo(), HDMI_GROUNDED)])
    assert [x.status for x in a] == ["VERIFIED", "VERIFIED"]
    assert overall_assessment(a).status == "VERIFIED"
    # each requirement is supported only by its own photo
    assert {s.seq for ep in a[0].endpoints for s in ep.support} == {1}
    assert {s.seq for ep in a[1].endpoints for s in ep.support} == {2}


def test_r1_verified_r2_violated_is_overall_violated(spec):
    a = assess(spec, [rec(1, ETH_PHOTO, ETH_GROUNDED), rec(2, hdmi_photo(tv_occ="empty"), {"P1": HDMI})])
    assert [x.status for x in a] == ["VERIFIED", "VIOLATED"]
    o = overall_assessment(a)
    assert o.status == "VIOLATED" and "R2" in o.explanation


def test_overall_is_none_before_any_assessment_and_mirrors_a_single_requirement(spec):
    assert overall_assessment([]) is None
    single = assess_requirement(spec, spec.requirements[0], [rec(1, ETH_PHOTO, ETH_GROUNDED)])
    assert overall_assessment([single]).status == single.status


# ----------------------------------------------------------------------- 5-6. no conflation across requirements

def test_photo_proving_ethernet_establishes_nothing_for_hdmi(spec):
    a = assess(spec, [rec(1, ETH_PHOTO, ETH_GROUNDED)])
    r2 = a[1]
    assert all(not ep.support and not ep.conflicts for ep in r2.endpoints)
    assert r2.identity_state == "unknown"
    assert {g.code for g in r2.gaps} == {"PORT_NOT_FOUND", "DEVICE_NOT_SEEN"}  # console seen, TV never seen


def test_grounding_for_one_cable_concept_does_not_support_the_other(spec):
    # Muse places matching plugs in both console ports, but SAM only grounded the Ethernet cable there.
    ext = extraction(devices=[device("D1", "ps5"), device("D2", "tv")],
                     ports=[cport("P1", "D1", "HDMI OUT", "hdmi", color="black"),
                            cport("P2", "D2", "HDMI 2", "hdmi", color="black", box=(600, 400, 660, 480))],
                     cables=[ccable("C1", "black", ["P1", "P2"], "hdmi")])
    r2 = assess_requirement(spec, spec.requirements[1], [rec(1, ext, {"P1": ETH, "P2": ETH})])
    assert r2.status == "INSUFFICIENT_EVIDENCE"
    assert {g.code for g in r2.gaps} == {"GROUNDING_MISSING"}


def test_same_colour_cables_of_different_types_are_not_conflated(spec):
    # Both cables black; R1 asserts its (Ethernet) cable is unique. The black plug in the console's HDMI OUT port
    # is an HDMI plug: it must not count as "the unique black Ethernet cable in the wrong port".
    s = variant(spec, "R1", cable_color="black", cable_identity="unique_in_installation")
    for conn in ("hdmi", "unclear"):  # explicit other family, or unknown on a mixed-family device
        ext = extraction(devices=[device("D1", "ps5")],
                         ports=[cport("P1", "D1", "HDMI OUT", conn, color="black")],
                         cables=[ccable("C1", "black", ["P1"], conn, path="partially_visible")])
        r1 = assess_requirement(s, s.requirements[0], [rec(1, ext, {"P1": "black ethernet cable"})])
        assert r1.status == "INSUFFICIENT_EVIDENCE", (conn, r1.explanation)
        assert all(not ep.conflicts for ep in r1.endpoints)


def test_a_cable_reported_as_hdmi_never_proves_the_ethernet_run(spec):
    # A cable Muse reports as HDMI, "traced" between the router LAN 2 and console LAN ports, is not the Ethernet
    # cable: no identity, no colour borrowed through it.
    ext = extraction(devices=[device("D1", "router"), device("D2", "ps5")],
                     ports=[cport("P1", "D1", "2", "ethernet", group="LAN", color="clear"),
                            cport("P2", "D2", "LAN", "ethernet", color="clear", box=(600, 400, 660, 480))],
                     cables=[ccable("C1", "blue", ["P1", "P2"], "hdmi")])
    r1 = assess_requirement(spec, spec.requirements[0], [rec(1, ext, ETH_GROUNDED)])
    assert r1.status == "INSUFFICIENT_EVIDENCE"
    assert r1.identity_state == "unknown" and not r1.identity_evidence
    assert all(not ep.support for ep in r1.endpoints)


def test_a_port_reported_as_another_connector_family_is_not_the_endpoint(spec):
    # Label read as "LAN" but the socket is reported as HDMI: never support, never violation for R1.
    ext = extraction(devices=[device("D1", "ps5")], ports=[cport("P1", "D1", "LAN", "hdmi", occ="empty", color=None)])
    r1 = assess_requirement(spec, spec.requirements[0], [rec(1, ext)])
    assert r1.status == "INSUFFICIENT_EVIDENCE"
    assert r1.endpoints[1].gap.code == "PORT_NOT_FOUND"


# ------------------------------------------------------------------------------------ 7. unreadable labels

def test_icon_only_console_ports_cannot_be_verified(spec):
    # The console's ports carry no readable printed text (e.g. icons only). Plugs, colours and SAM all match.
    eth = extraction(devices=[device("D1", "router"), device("D2", "ps5")],
                     ports=[cport("P1", "D1", "2", "ethernet", group="LAN", color="blue"),
                            cport("P2", "D2", None, "ethernet", color="blue", legible="no_label",
                                  box=(600, 400, 660, 480))],
                     cables=[ccable("C1", "blue", ["P1", "P2"], "ethernet")])
    a = assess(spec, [rec(1, eth, ETH_GROUNDED), rec(2, hdmi_photo(console_label=None, legible="no_label"),
                                                     HDMI_GROUNDED)])
    assert [x.status for x in a] == ["INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE"]
    assert a[0].endpoints[1].gap.code == "LABEL_ILLEGIBLE" and a[1].endpoints[0].gap.code == "LABEL_ILLEGIBLE"
    assert overall_assessment(a).status == "INSUFFICIENT_EVIDENCE"


# ------------------------------------------------------------------------------------------- 8. guidance

def test_gap_selection_moves_to_the_unresolved_requirement(spec):
    a = assess(spec, [rec(1, ETH_PHOTO, ETH_GROUNDED)])
    g = select_gap(a, set(), {"router", "ps5"})
    assert g.requirement_id == "R2" and g.target.startswith("Test Console")  # console is in view: start there


def test_agent_asks_for_hdmi_evidence_once_ethernet_is_verified(spec):
    fm = FakeMeta()
    fm.sam[ETH] = sam_record(0, (80, 120, 270, 150))  # one mask reaching both Ethernet port regions
    fm.queue_chat(OBS, ETH_PHOTO)
    fm.queue_chat(PLAN, plan("Move to the back of the console and frame its HDMI port with any label readable.",
                             action="move_to_rear"))
    s = settings()
    ag = InspectionAgent(spec, fm.client(s), s)
    step = asyncio.run(ag.observe(make_image("overview.jpg", color=(10, 20, 30))))
    assert [a.status for a in step.assessments] == ["VERIFIED", "INSUFFICIENT_EVIDENCE"]
    assert step.next_view is not None and step.next_view.requirement_id == "R2"
    assert step.stop_reason is None
    # both cable concepts were segmented in the same photo: each requirement grounds its own cable
    sam_concepts = [json.loads(r.content)["input"][0]["content"][0]["text"] for r in fm.requests
                    if r.url.path.endswith("/responses")]
    assert ETH in sam_concepts and HDMI in sam_concepts


# --------------------------------------------------------------------------------------- 9. contradictions

def test_contradiction_in_one_requirement_stays_visible_next_to_the_other(spec):
    obs = [rec(1, ETH_PHOTO, ETH_GROUNDED), rec(2, hdmi_photo(), HDMI_GROUNDED),
           rec(3, hdmi_photo(tv_occ="empty"), {"P1": HDMI})]
    a = assess(spec, obs)
    assert a[0].status == "VERIFIED"
    assert a[1].status == "INSUFFICIENT_EVIDENCE" and a[1].contradictions
    o = overall_assessment(a)
    assert o.status == "INSUFFICIENT_EVIDENCE" and o.review_required == ["R2"]
    assert "review" in o.explanation


def test_violation_elsewhere_does_not_hide_a_contradiction(spec):
    # R1 contradicted (photos disagree on the router port), R2 violated: overall VIOLATED, review still listed.
    empty_router = extraction(devices=[device("D1", "router")],
                              ports=[cport("P1", "D1", "2", "ethernet", group="LAN", occ="empty", color=None)])
    a = assess(spec, [rec(1, ETH_PHOTO, ETH_GROUNDED), rec(2, empty_router), rec(3, hdmi_photo(tv_occ="empty"),
                                                                                 {"P1": HDMI})])
    assert [x.status for x in a] == ["INSUFFICIENT_EVIDENCE", "VIOLATED"]
    o = overall_assessment(a)
    assert o.status == "VIOLATED" and o.review_required == ["R1"]


def test_agent_blocks_only_the_contradicted_requirement(spec):
    fm = FakeMeta()
    s = settings()
    ag = InspectionAgent(spec, fm.client(s), s)
    ag.observations = [rec(1, hdmi_photo(), HDMI_GROUNDED), rec(2, hdmi_photo(tv_occ="empty"), {"P1": HDMI})]
    ag._assess()
    assert [r["requirement_id"] for r in ag.review_items()] == ["R2"]


# ---------------------------------------------------------------------- 10-11. reports, API, caps, idempotency

def test_markdown_report_states_the_overall_verdict_for_multi_requirement_specs(spec):
    fm = FakeMeta()
    s = settings()
    ag = InspectionAgent(spec, fm.client(s), s)
    ag.observations = [rec(1, ETH_PHOTO, ETH_GROUNDED)]
    ag._assess()
    md = render_markdown(ag, {}, {"model_calls": 0, "estimated_cost_usd": 0.0})
    assert "## Overall installation verdict" in md and "[INSUFFICIENT EVIDENCE]" in md
    assert md.index("## Overall installation verdict") < md.index("## Final verdict")


def test_api_reports_overall_verdict_and_keeps_cap_and_idempotency(tmp_path, spec):
    fm = FakeMeta()
    fm.sam[ETH] = sam_record(0, (80, 120, 270, 150))
    fm.queue_chat(OBS, ETH_PHOTO)
    fm.queue_chat(PLAN, plan("Move to the back of the console and frame its HDMI port with any label readable."))

    async def go():
        store = Store(tmp_path / "var" / "proofcam.db")
        app = create_app(settings(), store, httpx.MockTransport(fm.handler),
                         config=ServiceConfig(model_source="mock", global_call_limit=20))
        try:
            async with app.router.lifespan_context(app):
                t = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
                async with httpx.AsyncClient(transport=t, base_url="http://127.0.0.1:8000") as c:
                    r = await c.post("/api/inspections", json={"spec": json.loads(spec.model_dump_json())})
                    assert r.status_code == 201 and r.json()["overall"] is None
                    iid = r.json()["id"]
                    r1 = await c.post(f"/api/inspections/{iid}/captures", **upload("overview.jpg"),
                                      headers={"Idempotency-Key": "k1"})
                    assert r1.status_code == 200, r1.text
                    body = r1.json()
                    assert body["overall"]["status"] == "INSUFFICIENT_EVIDENCE"
                    assert body["overall"]["requirement_statuses"] == {"R1": "VERIFIED", "R2": "INSUFFICIENT_EVIDENCE"}
                    assert body["next_view"]["requirement_id"] == "R2"
                    n = len(fm.requests)
                    r2 = await c.post(f"/api/inspections/{iid}/captures", **upload("overview.jpg"),
                                      headers={"Idempotency-Key": "k1"})
                    assert r2.json()["replayed"] is True and len(fm.requests) == n  # no new paid calls
                    st = (await c.get(f"/api/inspections/{iid}")).json()
                    assert st["overall"] == body["overall"] and store.total_model_calls() == n <= 20
                    rep = (await c.get(f"/api/inspections/{iid}/report?format=json")).json()
                    assert rep["overall"]["status"] == "INSUFFICIENT_EVIDENCE"
        finally:
            store.close()

        # The server-wide cap still refuses a capture before any model call.
        store2 = Store(tmp_path / "var" / "capped.db")
        app2 = create_app(settings(), store2, httpx.MockTransport(fm.handler),
                          config=ServiceConfig(model_source="mock", global_call_limit=7))
        try:
            async with app2.router.lifespan_context(app2):
                t = httpx.ASGITransport(app=app2, client=("127.0.0.1", 1))
                async with httpx.AsyncClient(transport=t, base_url="http://127.0.0.1:8000") as c:
                    iid = (await c.post("/api/inspections", json={"spec": json.loads(spec.model_dump_json())})).json()["id"]
                    before = len(fm.requests)
                    r = await c.post(f"/api/inspections/{iid}/captures", **upload("x.jpg"),
                                     headers={"Idempotency-Key": "k2"})
                    assert err(r) == (429, "spend_cap_reached") and len(fm.requests) == before
        finally:
            store2.close()
    asyncio.run(go())


def test_specs_route_lists_real_specs_but_never_the_draft_folder(tmp_path):
    async def go():
        store = Store(tmp_path / "s.db")
        app = create_app(settings(), store, httpx.MockTransport(FakeMeta().handler),
                         config=ServiceConfig(model_source="mock"))
        try:
            async with app.router.lifespan_context(app):
                t = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
                async with httpx.AsyncClient(transport=t, base_url="http://127.0.0.1:8000") as c:
                    ids = [s["spec_id"] for s in (await c.get("/api/specs")).json()]
                    assert {"my_setup", "router_switch", "ps5_home_setup"} <= set(ids)
                    assert len(ids) == len(set(ids)) and not any("draft" in i for i in ids)
        finally:
            store.close()
    asyncio.run(go())
