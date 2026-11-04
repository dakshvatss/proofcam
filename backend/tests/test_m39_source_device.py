"""M3.9: the operator-assisted Home template accepts an Ethernet source device that is a router, gateway, Jio set-top
box or media receiver (an intentional spec change for this installation). Hand-built mocked model claims only; no
network, no paid calls.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fakes import device, extraction
from proofcam.prompts import observe_user_text
from proofcam.report import render_markdown
from proofcam.spec import InspectionSpec
from test_m37_evidence import ETH, HDMI, HOME, a_of, assess_all, decl, feed, replay_agent
from test_multi_requirement import cport, rec

SPECS = Path(__file__).resolve().parents[2] / "data" / "specs"
STB = InspectionSpec.load(SPECS / "ps5_home_setup_assisted.json")


def jio_box(seq, label=None, legible="no_label", color="white", grounded=True, conn="ethernet", occ="cable_inserted"):
    """A dark navy Jio set-top box with ONE RJ45 socket (no printed label by default) holding a white cable."""
    d = device("D1", "source")
    d["identification_basis"] = "dark navy box with Jio logo; set-top box with one RJ45 socket on its rear"
    return rec(seq, extraction(devices=[d], ports=[cport("P1", "D1", label, conn, color=color if occ != "empty" else None,
                                                         legible=legible, occ=occ)]),
               {"P1": ETH} if grounded and occ == "cable_inserted" else None)


def ps5_rear(seq):
    return rec(seq, extraction(devices=[device("D1", "ps5")], ports=[
        cport("P1", "D1", None, "ethernet", color="white", legible="no_label"),
        cport("P2", "D1", None, "hdmi", color="black", legible="no_label", box=(200, 600, 260, 680))]),
        {"P1": ETH, "P2": HDMI})


def tv_unnumbered(seq):
    return rec(seq, extraction(devices=[device("D1", "tv")], ports=[
        cport("P1", "D1", None, "hdmi", color="black", legible="illegible")]), {"P1": HDMI})


def test_spec_names_the_source_generically_and_only_the_assisted_template_changed():
    assert [d.id for d in STB.devices] == ["source", "ps5", "tv"]
    assert STB.device("source").name == "Ethernet-capable source device"
    assert "Jio set-top box" in STB.device("source").description and "never call a set-top box a router" in \
        STB.device("source").description
    assert all(r.cable_color is None for r in STB.requirements)
    assert HOME.device("router").name == "Wi-Fi Router" and HOME.assisted is None  # strict template untouched


def test_jio_box_single_unlabelled_socket_and_white_cable_verify_r1_with_disclosure():
    out = assess_all(STB, [jio_box(1), ps5_rear(2)], [decl("cable_identity", requirement_id="R1")])
    r1 = a_of(out, "R1")
    assert [ep.state for ep in r1.endpoints] == ["established", "established"]
    assert r1.endpoints[0].support[0].port_basis == "connector_shape"  # no LAN 1-4 label needed
    assert r1.status == "VERIFIED" and r1.assurance == "operator_assisted"
    assert any("Ethernet-capable source device" in x and "socket shape" in x for x in r1.assumptions)


def test_a_router_with_a_labelled_lan_port_is_equally_accepted():
    router = rec(1, extraction(devices=[device("D1", "source")],
                               ports=[cport("P1", "D1", "LAN 3", "ethernet", color="blue")]), {"P1": ETH})
    assert a_of(assess_all(STB, [router, ps5_rear(2)]), "R1").endpoints[0].state == "established"


def test_a_socket_legibly_labelled_wan_never_satisfies_r1():
    wan = jio_box(1, label="WAN", legible="legible")
    ep = a_of(assess_all(STB, [wan, ps5_rear(2)]), "R1").endpoints[0]
    assert ep.state == "unknown" and not ep.support


def test_hdmi_plug_or_empty_socket_on_the_source_does_not_establish_r1():
    for photo in (jio_box(1, conn="hdmi"), jio_box(1, occ="empty")):
        assert a_of(assess_all(STB, [photo, ps5_rear(2)]), "R1").endpoints[0].state != "established"


def test_tv_input_with_unreadable_numbering_establishes_r2_and_both_requirements_are_independent():
    out = assess_all(STB, [ps5_rear(2), tv_unnumbered(3)], [decl("cable_identity", requirement_id="R2")])
    assert a_of(out, "R2").status == "VERIFIED"
    assert a_of(out, "R1").status == "INSUFFICIENT_EVIDENCE"  # no source device photographed yet


def test_full_stb_installation_verifies_operator_assisted_and_report_shows_the_actual_category():
    ag = replay_agent(STB)
    feed(ag, jio_box(1), ps5_rear(2), tv_unnumbered(3))
    for rid in ("R1", "R2"):
        asyncio.run(ag.declare("cable_identity", requirement_id=rid))
    assert [a.status for a in ag.assessments] == ["VERIFIED", "VERIFIED"]
    md = render_markdown(ag, {}, ag.trace.summary())
    assert "[VERIFIED — OPERATOR-ASSISTED]" in md
    assert "matched to Ethernet-capable source device (clear); Muse's description: dark navy box with Jio logo; set-top box" in md
    assert "Wi-Fi Router" not in md  # the strict template's device name never appears


def test_muse_is_given_the_accepted_categories():
    text = observe_user_text(STB)
    assert "Jio set-top box" in text and "Wi-Fi router" in text


def test_tv_is_generic_no_logo_and_no_readable_port_label_needed():
    tv = STB.device("tv")
    assert tv.name == "Television" and "Samsung" not in tv.description and "No logo" in tv.description
    panel_only = rec(4, extraction(devices=[device("D1", "tv", side="rear")], ports=[
        cport("P1", "D1", None, "hdmi", color="black", legible="no_label")]), {"P1": HDMI})
    ep = a_of(assess_all(STB, [panel_only]), "R2").endpoints[1]
    assert ep.state == "established" and ep.support[0].port_basis == "connector_shape"
    # The plug must still be in an HDMI-shaped socket: a socket Muse reports as another family never counts.
    usb = rec(4, extraction(devices=[device("D1", "tv")], ports=[cport("P1", "D1", None, "usb", color="black")]))
    assert a_of(assess_all(STB, [usb]), "R2").endpoints[1].state == "unknown"


def test_device_descriptions_never_tell_muse_that_a_cable_is_plugged_in():
    # Descriptions are sent to Muse with every photo; the expected installation state must never be in them.
    for d in STB.devices:
        text = d.description.lower()
        assert "cable is connected" not in text and "cable in" not in text and "plugged" not in text, d.id
