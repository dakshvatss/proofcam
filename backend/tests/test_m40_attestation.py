"""M4.0: written operator attestation for an endpoint the photos could not establish (assisted template only).

Hand-built mocked model claims; no network, no paid calls.
"""

from __future__ import annotations

import asyncio

import pytest

from fakes import device, extraction
from proofcam.policy import overall_assessment
from proofcam.report import render_markdown
from test_m37_evidence import HOME, a_of, assess_all, decl, feed, replay_agent
from test_m39_source_device import STB, jio_box, ps5_rear, tv_unnumbered
from test_multi_requirement import cport, rec

NOTE = "Looked behind the TV: HDMI cable firmly pushed into the second HDMI input."


def test_attestation_establishes_an_end_no_photo_could_and_is_labelled_attested():
    ag = replay_agent(STB)
    feed(ag, jio_box(1), ps5_rear(2))  # the TV end was never photographed usefully
    gap = a_of(ag.assessments, "R2").endpoints[1].gap
    assert gap.context["attestation_permitted"] is True
    d = asyncio.run(ag.declare("endpoint_attestation", requirement_id="R2", endpoint_index=1, note=NOTE))
    assert d.note == NOTE and d.statement.startswith("I checked the Television any HDMI input end myself")
    ep = a_of(ag.assessments, "R2").endpoints[1]
    assert ep.state == "established" and ep.support[0].attested and ep.support[0].seq == 0
    for rid in ("R1", "R2"):
        asyncio.run(ag.declare("cable_identity", requirement_id=rid))
    r2 = a_of(ag.assessments, "R2")
    assert r2.status == "VERIFIED" and r2.assurance == "operator_attested"
    assert any(NOTE in x for x in r2.operator_declarations)
    assert overall_assessment(ag.assessments).assurance == "operator_attested"
    assert a_of(ag.assessments, "R1").assurance == "operator_assisted"  # R1 rests on photos + the cable statement
    md = render_markdown(ag, {}, ag.trace.summary())
    assert "[VERIFIED — OPERATOR-ATTESTED, NOT VISUALLY ESTABLISHED] R2" in md
    assert "written attestation by the operator; NO photo evidence" in md and NOTE in md


def test_attestation_never_overrides_a_visibly_empty_or_wrong_socket():
    empty_tv = rec(3, extraction(devices=[device("D1", "tv")],
                                 ports=[cport("P1", "D1", None, "hdmi", occ="empty", color=None, legible="no_label")]))
    plug = ps5_rear(2)
    ag = replay_agent(STB)
    # PS5 HDMI socket: plug in photo 2, a second photo shows that single socket empty -> contradicted
    empty_ps5 = rec(4, extraction(devices=[device("D1", "ps5")],
                                  ports=[cport("P2", "D1", None, "hdmi", occ="empty", color=None, legible="no_label")]))
    feed(ag, jio_box(1), plug, empty_tv, empty_ps5)
    with pytest.raises(ValueError, match="already established|contrary evidence"):
        asyncio.run(ag.declare("endpoint_attestation", requirement_id="R2", endpoint_index=0, note=NOTE))
    ps5 = a_of(ag.assessments, "R2").endpoints[0]
    assert ps5.state == "contradicted"
    # injected anyway: the policy keeps the contradiction
    out = assess_all(STB, [jio_box(1), plug, empty_ps5],
                     [decl("endpoint_attestation", requirement_id="R2", endpoint_index=0, note=NOTE)])
    assert a_of(out, "R2").endpoints[0].state == "contradicted"
    # an HDMI plug in the source's RJ45 socket is still never R1's plug, attested or not, once photos show it
    wrong = jio_box(1, label="WAN", legible="legible")
    assert a_of(assess_all(STB, [wrong]), "R1").endpoints[0].state == "unknown"


def test_attestation_needs_a_real_note_and_an_assisted_template_that_allows_it():
    ag = replay_agent(STB)
    feed(ag, ps5_rear(1))
    with pytest.raises(ValueError, match="10 to 500"):
        asyncio.run(ag.declare("endpoint_attestation", requirement_id="R2", endpoint_index=1, note="ok"))
    for spec in (HOME,):
        strict = replay_agent(spec)
        feed(strict, ps5_rear(1))
        with pytest.raises(ValueError, match="does not permit"):
            asyncio.run(strict.declare("endpoint_attestation", requirement_id="R2", endpoint_index=1, note=NOTE))
        injected = assess_all(spec, [ps5_rear(1)],
                              [decl("endpoint_attestation", requirement_id="R2", endpoint_index=1, note=NOTE)])
        assert a_of(injected, "R2").endpoints[1].state == "unknown"
        assert "attestation_permitted" not in a_of(injected, "R2").endpoints[1].gap.context


def test_photo_evidence_keeps_precedence_and_attestation_is_not_needed_when_photos_suffice():
    out = assess_all(STB, [jio_box(1), ps5_rear(2), tv_unnumbered(3)],
                     [decl("cable_identity", requirement_id="R2"),
                      decl("endpoint_attestation", requirement_id="R2", endpoint_index=1, note=NOTE)])
    r2 = a_of(out, "R2")
    assert r2.status == "VERIFIED" and r2.assurance == "operator_assisted"  # the TV photo, not the note
    assert not any(s.attested for s in r2.endpoints[1].support)
