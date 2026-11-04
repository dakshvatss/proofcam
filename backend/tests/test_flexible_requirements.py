"""Flexible endpoints (any permitted port), any-colour cables, per-spec photo budget (M3.5).

Mocked model claims only (no network, NOT real inference). The spec under test is the real, loadable
data/specs/ps5_home_setup.json; observations are hand-built claims, not photos of real hardware.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from fakes import FakeMeta, device, extraction, make_image, plan, sam_record, settings
from proofcam.agent import InspectionAgent
from proofcam.api import create_app
from proofcam.policy import assess_requirement, mixed_connector_devices, overall_assessment
from proofcam.report import build_report, render_markdown
from proofcam.service import ServiceConfig
from proofcam.spec import InspectionSpec
from proofcam.store import Store
from test_multi_requirement import ccable, cport, rec

ROOT = Path(__file__).resolve().parents[2]
PS5 = ROOT / "data" / "specs" / "ps5_home_setup.json"
ETH, HDMI = "ethernet cable", "hdmi cable"
OBS, PLAN = "ObservationExtraction", "NextViewPlan"
RIGHT = (600, 400, 660, 480)


@pytest.fixture
def spec() -> InspectionSpec:
    return InspectionSpec.load(PS5)


def variant(spec: InspectionSpec, req_id: str, endpoint: int | None = None, endpoint_changes: dict | None = None,
            **changes) -> InspectionSpec:
    d = json.loads(spec.model_dump_json())
    for r in d["requirements"]:
        if r["id"] == req_id:
            r.update(changes)
            if endpoint is not None:
                r["endpoints"][endpoint].update(endpoint_changes or {})
    return InspectionSpec.model_validate(d)


def r1(spec, obs):
    return assess_requirement(spec, spec.requirements[0], obs)


def r2(spec, obs):
    return assess_requirement(spec, spec.requirements[1], obs)


def eth_photo(router_port=None, ps5_port=None, cables=None):
    """Router + console, one Ethernet run. Defaults: router 'LAN 3' (heading LAN), console socket identified only by
    its observed RJ45 shape (no printed text), a grey cable traced end to end."""
    rp = router_port or cport("P1", "D1", "3", "ethernet", group="LAN", color="grey")
    pp = ps5_port or cport("P2", "D2", None, "ethernet", color="grey", legible="no_label", box=RIGHT)
    return extraction(devices=[device("D1", "router"), device("D2", "ps5")], ports=[rp, pp],
                      cables=cables if cables is not None else [ccable("C1", "grey", ["P1", "P2"], "ethernet")])


def hdmi_photo(tv_port=None, ps5_port=None, cables=None):
    pp = ps5_port or cport("P1", "D1", None, "hdmi", color="black", legible="no_label")
    tp = tv_port or cport("P2", "D2", "HDMI 2", "hdmi", color="black", box=RIGHT)
    return extraction(devices=[device("D1", "ps5"), device("D2", "tv")], ports=[pp, tp],
                      cables=cables if cables is not None else [ccable("C1", "black", ["P1", "P2"], "hdmi")])


BOTH_ETH = {"P1": ETH, "P2": ETH}
BOTH_HDMI = {"P1": HDMI, "P2": HDMI}


# ------------------------------------------------------------------------------------- the active demo spec

def test_home_setup_spec_is_loadable_and_has_no_placeholders(spec):
    assert spec.title == "Home Entertainment Installation" and spec.max_photos == 8
    assert [d.id for d in spec.devices] == ["router", "ps5", "tv"]
    assert [(r.id, r.connector, r.cable_color, r.cable_identity) for r in spec.requirements] == [
        ("R1", "ethernet", None, "require_trace"), ("R2", "hdmi", None, "require_trace")]
    assert all(e.flexible for r in spec.requirements for e in r.endpoints)
    assert mixed_connector_devices(spec) == {"ps5"}
    assert "TODO" not in PS5.read_text(encoding="utf-8")


def test_spec_validation_rejects_unsafe_combinations(spec):
    with pytest.raises(ValidationError, match="unique_in_installation"):  # any colour + "the only cable"
        variant(spec, "R1", cable_identity="unique_in_installation")
    with pytest.raises(ValidationError, match="selector"):
        variant(spec, "R1", endpoint=0, endpoint_changes={"selector": {"excluded_labels": ["WAN"]}})
    with pytest.raises(ValidationError, match="label_aliases"):
        variant(spec, "R1", endpoint=0, endpoint_changes={"label_aliases": ["LAN 1"]})
    with pytest.raises(ValidationError):
        InspectionSpec.model_validate({**json.loads(spec.model_dump_json()), "max_photos": 11})


# ---------------------------------------------------------------------------------- flexible router LAN port

def test_any_lan_port_with_any_colour_cable_verifies_only_with_full_evidence(spec):
    a = r1(spec, [rec(1, eth_photo(), BOTH_ETH)])
    assert a.status == "VERIFIED", a.explanation
    assert a.identity_state == "established"
    assert [s.port_basis for s in a.endpoints[0].support] == ["direct_label"]
    assert [s.port_basis for s in a.endpoints[1].support] == ["connector_shape"]
    assert any("socket shape" in x for x in a.assumptions)  # the shape-based identity is disclosed
    assert "any cable colour accepted" in a.explanation


def test_wan_port_never_qualifies_as_a_lan_port(spec):
    a = r1(spec, [rec(1, eth_photo(router_port=cport("P1", "D1", "WAN", "ethernet", color="grey")), BOTH_ETH)])
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert not a.endpoints[0].support and a.identity_state == "unknown"


def test_unreadable_or_number_only_router_label_is_not_a_lan_port(spec):
    illegible = cport("P1", "D1", None, "ethernet", color="grey", legible="illegible")
    number_only = cport("P1", "D1", "3", "ethernet", color="grey")  # no 'LAN' heading: could be any port
    for port in (illegible, number_only):
        a = r1(spec, [rec(1, eth_photo(router_port=port), BOTH_ETH)])
        assert a.status == "INSUFFICIENT_EVIDENCE"
        assert a.endpoints[0].state == "unknown" and not a.endpoints[0].support


def test_an_empty_permitted_lan_port_is_not_a_violation(spec):
    empty = cport("P1", "D1", "1", "ethernet", occ="empty", color=None, group="LAN")
    o = extraction(devices=[device("D1", "router")], ports=[empty])
    a = r1(spec, [rec(1, o)])
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert a.endpoints[0].state == "unknown" and not a.endpoints[0].conflicts
    assert "another permitted port may hold it" in a.endpoints[0].gap.missing_fact


def test_a_permitted_port_holding_another_coloured_cable_is_not_a_violation(spec):
    blue = variant(spec, "R1", cable_color="blue")  # flexible ports with an exact colour
    other = cport("P1", "D1", "2", "ethernet", color="yellow", group="LAN")
    a = r1(blue, [rec(1, extraction(devices=[device("D1", "router")], ports=[other]), {"P1": "blue ethernet cable"})])
    assert a.status == "INSUFFICIENT_EVIDENCE" and not a.endpoints[0].conflicts


def test_finite_port_list_is_violated_only_when_every_listed_port_is_clearly_empty(spec):
    s = variant(spec, "R1", endpoint=0, endpoint_changes={
        "port_label": "LAN 1 or LAN 2", "selector": {"allowed_labels": ["LAN 1", "LAN 2"]}})
    one = extraction(devices=[device("D1", "router")],
                     ports=[cport("P1", "D1", "1", "ethernet", occ="empty", color=None, group="LAN")])
    both = extraction(devices=[device("D1", "router")],
                      ports=[cport("P1", "D1", "1", "ethernet", occ="empty", color=None, group="LAN"),
                             cport("P2", "D1", "2", "ethernet", occ="empty", color=None, group="LAN", box=RIGHT)])
    assert r1(s, [rec(1, one)]).status == "INSUFFICIENT_EVIDENCE"
    a = r1(s, [rec(1, both)])
    assert a.status == "VIOLATED" and len(a.endpoints[0].conflicts) == 2


# ------------------------------------------------------------------------------------- flexible TV input

def test_any_tv_hdmi_input_needs_an_observed_hdmi_socket(spec):
    assert r2(spec, [rec(1, hdmi_photo(), BOTH_HDMI)]).status == "VERIFIED"
    unclear = cport("P2", "D2", "HDMI 1", "unclear", color="black", box=RIGHT)  # label alone is not the shape
    out = cport("P2", "D2", "HDMI OUT", "hdmi", color="black", box=RIGHT)        # explicitly excluded
    for tv in (unclear, out):
        a = r2(spec, [rec(1, hdmi_photo(tv_port=tv), BOTH_HDMI)])
        assert a.status == "INSUFFICIENT_EVIDENCE"
        assert not a.endpoints[1].support


def test_an_empty_tv_input_is_not_a_violation(spec):
    empty = cport("P2", "D2", "HDMI 1", "hdmi", occ="empty", color=None, box=RIGHT)
    a = r2(spec, [rec(1, hdmi_photo(tv_port=empty, cables=[]), {"P1": HDMI})])
    assert a.status == "INSUFFICIENT_EVIDENCE" and not a.endpoints[1].conflicts


def test_uncertain_connector_type_on_the_console_never_identifies_its_port(spec):
    unclear = cport("P2", "D2", None, "unclear", color="grey", legible="no_label", box=RIGHT)
    a = r1(spec, [rec(1, eth_photo(ps5_port=unclear), BOTH_ETH)])
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[1].state == "unknown"


def test_console_hdmi_socket_never_counts_for_the_ethernet_requirement(spec):
    hd = cport("P2", "D2", None, "hdmi", color="black", legible="no_label", box=RIGHT)
    a = r1(spec, [rec(1, eth_photo(ps5_port=hd, cables=[ccable("C1", "black", ["P1", "P2"], "unclear")]),
                      BOTH_ETH)])
    assert a.status == "INSUFFICIENT_EVIDENCE" and not a.endpoints[1].support


# -------------------------------------------------------------------------------- cable identity, any colour

def test_any_colour_does_not_mean_any_cable(spec):
    # Two grey Ethernet cables, each seen at one end only: both ends supported, but no single photo shows ONE
    # cable between them.
    o = eth_photo(cables=[ccable("C1", "grey", ["P1"], "ethernet", path="partially_visible"),
                          ccable("C2", "grey", ["P2"], "ethernet", path="partially_visible")])
    a = r1(spec, [rec(1, o, BOTH_ETH)])
    assert [ep.state for ep in a.endpoints] == ["established", "established"]
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"
    assert {g.code for g in a.gaps} == {"CABLE_CONTINUITY"}


def test_any_colour_still_needs_the_cable_fully_traced(spec):
    o = eth_photo(cables=[ccable("C1", "grey", ["P1", "P2"], "ethernet", path="partially_visible")])
    a = r1(spec, [rec(1, o, BOTH_ETH)])
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"


def test_group_matching_needs_the_word_alone_or_followed_by_a_number(spec):
    s = variant(spec, "R2", endpoint=1, endpoint_changes={"port_label": "any HDMI input",
                                                         "selector": {"allowed_group": "HDMI"}})
    for label, ok in (("HDMI 2", True), ("HDMI 2 (ARC)", True), ("HDMI OUT", False), ("HDMIX", False)):
        tv = cport("P2", "D2", label, "hdmi", color="black", box=RIGHT)
        assert (r2(s, [rec(1, hdmi_photo(tv_port=tv), BOTH_HDMI)]).status == "VERIFIED") is ok, label


def test_excluded_labels_win_over_a_matching_group_heading(spec):
    # 'WAN' printed under a shared 'LAN' heading: the heading alone must not make it a LAN port.
    wan = cport("P1", "D1", "WAN", "ethernet", group="LAN", color="grey")
    a = r1(spec, [rec(1, eth_photo(router_port=wan), BOTH_ETH)])
    assert a.status == "INSUFFICIENT_EVIDENCE" and not a.endpoints[0].support


def test_a_traced_cable_needs_grounding_at_both_ports(spec):
    a = r1(spec, [rec(1, eth_photo(), {"P1": ETH})])
    assert a.status == "INSUFFICIENT_EVIDENCE"


# --------------------------------------------------------------------------------- whole installation

def test_whole_installation_verified_only_when_both_connections_are(spec):
    obs = [rec(1, eth_photo(), BOTH_ETH)]
    a = [r1(spec, obs), r2(spec, obs)]
    assert overall_assessment(a).status == "INSUFFICIENT_EVIDENCE"
    obs.append(rec(2, hdmi_photo(), BOTH_HDMI))
    a = [r1(spec, obs), r2(spec, obs)]
    assert [x.status for x in a] == ["VERIFIED", "VERIFIED"]
    assert overall_assessment(a).status == "VERIFIED"


def test_exact_specs_keep_their_semantics():
    rs = InspectionSpec.load(ROOT / "data" / "specs" / "router_switch.json")
    empty = extraction(devices=[device("D1", "router")],
                       ports=[cport("P1", "D1", "1", "ethernet", occ="empty", color=None, group="LAN")])
    assert assess_requirement(rs, rs.requirements[0], [rec(1, empty)]).status == "VIOLATED"


# -------------------------------------------------------------------------------- agent: budget and SAM

def _agent(spec, fm):
    s = settings()
    return InspectionAgent(spec, fm.client(s), s)


def test_spec_photo_budget_is_enforced(spec):
    small = InspectionSpec.model_validate({**json.loads(spec.model_dump_json()), "max_photos": 2})
    fm = FakeMeta()
    front = extraction(devices=[device("D1", "router", side="front", ports=False)])
    fm.queue_chat(OBS, front, front)
    fm.queue_chat(PLAN, plan("Walk to the back of the router and frame its port row so labels can be read."))
    ag = _agent(small, fm)
    asyncio.run(ag.observe(make_image("a.jpg", color=(1, 2, 3))))
    step = asyncio.run(ag.observe(make_image("b.jpg", color=(4, 5, 6))))
    assert step.stop_reason == "observation_budget_exhausted" and ag.max_observations == 2
    assert _agent(spec, FakeMeta()).max_observations == 8


def _sam_concepts(fm):
    return [json.loads(r.content)["input"][0]["content"][0]["text"] for r in fm.requests
            if r.url.path.endswith("/responses")]


def test_sam_cap_drops_only_cable_concepts_no_port_can_use(spec):
    three = [device("D1", "router"), device("D2", "ps5", box=(500, 100, 700, 700)), device("D3", "tv")]
    fm = FakeMeta()
    fm.sam[ETH] = sam_record(0, (80, 120, 270, 150))
    only_eth = extraction(devices=three, ports=[cport("P1", "D1", "3", "ethernet", group="LAN", color="grey"),
                                                cport("P2", "D2", None, "ethernet", legible="no_label", box=RIGHT)],
                          cables=[ccable("C1", "grey", ["P1", "P2"], "ethernet")])
    fm.queue_chat(OBS, only_eth)
    fm.queue_chat(PLAN, plan("Move to the side of the television and frame its HDMI inputs closely."))
    asyncio.run(_agent(spec, fm).observe(make_image("o.jpg", color=(7, 8, 9))))
    c = _sam_concepts(fm)
    assert len(c) == 4 and ETH in c and HDMI not in c  # no occupied HDMI-compatible port in this photo
    assert {"router", "game console", "television"} <= set(c)

    fm2 = FakeMeta()
    unclear = extraction(devices=three, ports=[cport("P1", "D3", "HDMI 1", "unclear", color="black")])
    fm2.queue_chat(OBS, unclear)
    fm2.queue_chat(PLAN, plan("Move closer to the television inputs so the plug shape can be seen clearly."))
    asyncio.run(_agent(spec, fm2).observe(make_image("u.jpg", color=(9, 8, 7))))
    c2 = _sam_concepts(fm2)
    assert len(c2) == 4 and ETH in c2 and HDMI in c2  # unknown family: both cable concepts stay


# ------------------------------------------------------------------------- reports, API, recovery, access

def test_report_matches_assessments_and_discloses_shape_identity(spec):
    ag = _agent(spec, FakeMeta())
    ag.observations = [rec(1, eth_photo(), BOTH_ETH), rec(2, hdmi_photo(), BOTH_HDMI)]
    ag._assess()
    rep = build_report(ag, "insp_x", {})
    assert rep["overall"]["requirement_statuses"] == {a["requirement_id"]: a["status"] for a in rep["requirements"]}
    md = render_markdown(ag, {}, {"model_calls": 0, "estimated_cost_usd": 0.0})
    assert "[VERIFIED]" in md and "socket shape" in md and "Overall installation verdict" in md


def test_home_setup_starts_free_lists_its_endpoints_and_recovers(tmp_path):
    async def go():
        store = Store(tmp_path / "h.db")
        fm = FakeMeta()
        app = create_app(settings(), store, httpx.MockTransport(fm.handler), config=ServiceConfig(model_source="mock"),
                         access_code="correct-horse-battery-staple")
        try:
            async with app.router.lifespan_context(app):
                t = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
                async with httpx.AsyncClient(transport=t, base_url="http://127.0.0.1:8000") as c:
                    assert (await c.get("/api/specs")).status_code == 401  # behind the access code
                    await c.post("/api/session", json={"access_code": "correct-horse-battery-staple"})
                    listed = {s["spec_id"]: s for s in (await c.get("/api/specs")).json()}
                    home = listed["ps5_home_setup"]
                    assert home["max_photos"] == 8 and home["devices"] == ["Wi-Fi Router", "PlayStation 5",
                                                                             "Samsung Television"]
                    assert home["requirements"][1]["endpoints"] == [
                        {"device": "PlayStation 5", "port": "HDMI OUT port", "flexible": True},
                        {"device": "Samsung Television", "port": "any HDMI input", "flexible": True}]
                    r = await c.post("/api/inspections", json={"spec_id": "ps5_home_setup"})
                    assert r.status_code == 201
                    st = r.json()
                    assert st["overall"] is None and st["assessments"] == [] and st["created_at"] > 0
                    assert [q["id"] for q in st["spec"]["requirements"]] == ["R1", "R2"]
                    again = (await c.get(f"/api/inspections/{st['id']}")).json()  # page refresh
                    assert again["id"] == st["id"] and again["created_at"] == st["created_at"]
                    assert fm.requests == []  # starting and reloading made no model calls
        finally:
            store.close()
    asyncio.run(go())
