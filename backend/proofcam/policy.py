"""Deterministic verification policy.

The model never sets a verdict. This module derives VERIFIED / VIOLATED / INSUFFICIENT_EVIDENCE
from per-image claims under explicit rules:

  Endpoint support   : a usable image where the spec device is identified with 'clear' certainty,
                       the port label is 'legible' and matches the spec, a cable is inserted with
                       'clear' visibility, the plug colour matches, and (by default) a SAM mask of
                       the required cable reaches the port region.
  Endpoint violation : same identification + legible matching label, and the port is clearly
                       empty or clearly holds a different-coloured plug; or, only when the spec
                       asserts the cable is unique, the required cable is clearly in another port.
  Contradiction      : support and violation for the same endpoint -> never resolved silently.
  Cable identity     : both endpoints in ONE image with the cable fully traced between them, or an
                       explicit spec assertion (disclosed as an assumption). Similar-looking cables in
                       different images are never assumed to be the same cable.
  VERIFIED           : both endpoints supported AND identity established. Anything less is
                       INSUFFICIENT_EVIDENCE unless there is an uncontradicted violation.
"""

from __future__ import annotations

import re

from .evidence import (
    EndpointAssessment,
    EvidenceItem,
    Gap,
    ObservationRecord,
    RequirementAssessment,
)
from .observation import PortObservation, SeenDevice
from .spec import ConnectionRequirement, EndpointSpec, InspectionSpec, normalize_label

_COLOR_WORDS = {
    "red": "red", "maroon": "red", "crimson": "red",
    "orange": "orange",
    "yellow": "yellow", "gold": "yellow",
    "green": "green", "lime": "green",
    "blue": "blue", "navy": "blue",
    "purple": "purple", "violet": "purple",
    "pink": "pink", "magenta": "pink",
    "white": "white", "black": "black",
    "gray": "gray", "grey": "gray", "silver": "gray",
    "brown": "brown",
}


def base_color(c: str | None) -> str | None:
    """Map a free-text colour to one base colour; None if unknown or ambiguous ('blue/white')."""
    if not c:
        return None
    found = {_COLOR_WORDS[w] for w in re.findall(r"[a-z]+", c.lower()) if w in _COLOR_WORDS}
    return found.pop() if len(found) == 1 else None


def label_matches(p: PortObservation, e: EndpointSpec) -> bool:
    if p.label_legibility != "legible" or not p.label_read:
        return False
    accepted = e.accepted_labels()
    cands = {normalize_label(p.label_read)}
    if p.label_group:
        cands.add(normalize_label(f"{p.label_group} {p.label_read}"))
    return bool(cands & accepted)


def _port_desc(p: PortObservation) -> str:
    lab = f"{p.label_group + ' ' if p.label_group else ''}{p.label_read or '?'}"
    return f"port '{lab}' ({p.occupancy}, plug={p.plug_color or 'n/a'}, visibility={p.insertion_visibility})"


def _device_hits(obs: list[ObservationRecord], device_id: str, certainty: str = "clear"):
    for o in obs:
        if not o.usable:
            continue
        for d in o.extraction.devices:  # type: ignore[union-attr]
            if d.spec_device_id == device_id and d.identification_certainty == certainty:
                yield o, d


def assess_endpoint(spec: InspectionSpec, req: ConnectionRequirement, idx: int,
                    obs: list[ObservationRecord], require_grounding: bool) -> EndpointAssessment:
    e = req.endpoints[idx]
    dev = spec.device(e.device_id)
    target = f"{dev.name} port {e.port_label}"
    want = base_color(req.cable_color)
    concept = req.cable_concept()
    support: list[EvidenceItem] = []
    weak: list[EvidenceItem] = []
    conflicts: list[EvidenceItem] = []
    unclear_matches: list[EvidenceItem] = []
    illegible_ports = 0
    ports_seen = 0
    sides: set[str] = set()

    hits: list[tuple[ObservationRecord, SeenDevice]] = list(_device_hits(obs, e.device_id))
    for o, d in hits:
        sides.add(d.visible_side)
        for p in o.extraction.ports:  # type: ignore[union-attr]
            if p.device_ref != d.ref:
                continue
            ports_seen += 1
            if p.label_legibility in ("partially_legible", "illegible"):
                illegible_ports += 1
            item = EvidenceItem(seq=o.seq, image_id=o.image_id, port_ref=p.ref, device_ref=d.ref,
                                claim=f"{dev.name} {_port_desc(p)}",
                                grounding=o.port_links.get(f"{p.ref}|{concept}"))
            clear = p.insertion_visibility == "clear"
            got = base_color(p.plug_color)
            if label_matches(p, e):
                if clear and p.occupancy == "empty":
                    conflicts.append(item.model_copy(update={"claim": item.claim + " -> target port is empty"}))
                elif clear and p.occupancy == "cable_inserted" and got and want and got != want:
                    conflicts.append(item.model_copy(update={
                        "claim": item.claim + f" -> holds a {got} plug, not {want}"}))
                elif clear and p.occupancy == "cable_inserted" and got and got == want:
                    grounded = item.grounding is not None and item.grounding.corroborated
                    (support if grounded or not require_grounding else weak).append(item)
                else:
                    unclear_matches.append(item)
            elif (req.cable_identity == "unique_in_installation" and p.label_legibility == "legible"
                  and clear and p.occupancy == "cable_inserted" and got and got == want):
                conflicts.append(item.model_copy(update={
                    "claim": item.claim + f" -> the (spec-unique) {want} cable is in the wrong port"}))

    def gap(code, fact, **ctx) -> Gap:
        return Gap(requirement_id=req.id, code=code, endpoint_index=idx, target=target,
                   missing_fact=fact, context={"device": dev.name, "device_description": dev.description,
                                               "port_label": e.port_label, **ctx})

    claimed_support = support + weak
    if claimed_support and conflicts:
        return EndpointAssessment(index=idx, device_id=e.device_id, port_label=e.port_label,
                                  state="contradicted", support=claimed_support, conflicts=conflicts,
                                  gap=gap("CONTRADICTION",
                                          f"Observations of {target} conflict; a clear, close view is needed.",
                                          images=sorted({x.image_id for x in claimed_support + conflicts})))
    if support:
        return EndpointAssessment(index=idx, device_id=e.device_id, port_label=e.port_label,
                                  state="established", support=support)
    if conflicts:
        return EndpointAssessment(index=idx, device_id=e.device_id, port_label=e.port_label,
                                  state="violated", conflicts=conflicts)
    if weak:
        g = gap("GROUNDING_MISSING",
                f"Muse reports a {req.cable_color} plug in {target}, but SAM did not segment a "
                f"'{concept}' reaching that port; a closer, unobstructed view is needed.")
    elif unclear_matches:
        g = gap("INSERTION_UNCLEAR",
                f"{target} was found, but whether a {req.cable_color} plug is clearly inserted is not visible.")
    elif not hits:
        uncertain = any(True for _ in _device_hits(obs, e.device_id, "uncertain"))
        g = gap("DEVICE_NOT_SEEN",
                f"The {dev.name} has not been identified with certainty in any photo.",
                seen_uncertain=uncertain)
    elif ports_seen == 0:
        g = gap("PORTS_NOT_VISIBLE", f"The {dev.name}'s connection ports have not been visible.",
                sides_seen=sorted(sides))
    elif illegible_ports:
        g = gap("LABEL_ILLEGIBLE",
                f"Ports on the {dev.name} were seen, but labels were not legible enough to find {e.port_label}.",
                sides_seen=sorted(sides))
    else:
        g = gap("PORT_NOT_FOUND", f"No observed port on the {dev.name} was legibly labelled {e.port_label}.",
                sides_seen=sorted(sides))
    return EndpointAssessment(index=idx, device_id=e.device_id, port_label=e.port_label,
                              state="unknown", support=[], conflicts=[], gap=g)


def assess_requirement(spec: InspectionSpec, req: ConnectionRequirement, obs: list[ObservationRecord],
                       require_grounding: bool = True) -> RequirementAssessment:
    eps = [assess_endpoint(spec, req, i, obs, require_grounding) for i in range(2)]
    gaps = [ep.gap for ep in eps if ep.gap]
    contradictions = [f"{ep.device_id} {ep.port_label}: "
                      + "; ".join(f"[{x.image_id}] {x.claim}" for x in ep.support + ep.conflicts)
                      for ep in eps if ep.state == "contradicted"]
    assumptions: list[str] = []
    identity_state = "not_evaluated"
    identity_ev: list[EvidenceItem] = []

    violated = [ep for ep in eps if ep.state == "violated"]
    if violated:
        why = "; ".join(c.claim for ep in violated for c in ep.conflicts)
        return RequirementAssessment(requirement_id=req.id, status="VIOLATED",
                                     explanation=f"Clearly observed: {why}.", endpoints=eps,
                                     identity_state=identity_state, gaps=gaps,
                                     contradictions=contradictions)

    if all(ep.state == "established" for ep in eps):
        if req.cable_identity == "unique_in_installation":
            identity_state = "assumed_by_spec"
            assumptions.append(f"Spec asserts exactly one {req.cable_color} {req.cable_type} exists, so the "
                               "two endpoint observations are treated as the same cable.")
        else:
            want = base_color(req.cable_color)
            for o in obs:
                if not o.usable:
                    continue
                p0 = {s.port_ref for s in eps[0].support if s.seq == o.seq}
                p1 = {s.port_ref for s in eps[1].support if s.seq == o.seq}
                for c in o.extraction.cables:  # type: ignore[union-attr]
                    if (c.path_visibility == "fully_traced" and base_color(c.color) == want
                            and p0 & set(c.connected_port_refs) and p1 & set(c.connected_port_refs)):
                        identity_state = "established"
                        identity_ev.append(EvidenceItem(seq=o.seq, image_id=o.image_id,
                                                        claim=f"{c.color} cable {c.ref} traced continuously "
                                                              f"between ports {c.connected_port_refs}"))
            if identity_state != "established":
                identity_state = "unknown"
                gaps.append(Gap(requirement_id=req.id, code="CABLE_CONTINUITY", endpoint_index=None,
                                target=f"the {req.cable_color} cable run between both endpoints",
                                missing_fact=("Both ends show a matching plug, but no single photo shows the "
                                              "same cable running continuously between them."),
                                context={"endpoints": [f"{spec.device(x.device_id).name} {x.port_label}"
                                                       for x in req.endpoints]}))
        if identity_state in ("established", "assumed_by_spec"):
            return RequirementAssessment(
                requirement_id=req.id, status="VERIFIED",
                explanation="Both endpoints observed with legible labels, clear insertion and matching colour"
                            + (", SAM-grounded" if require_grounding else "")
                            + ("; cable identity traced in one image." if identity_state == "established"
                               else "; cable identity relies on a spec assertion."),
                endpoints=eps, identity_state=identity_state, identity_evidence=identity_ev,
                assumptions=assumptions)

    missing = "; ".join(g.missing_fact for g in gaps)
    return RequirementAssessment(requirement_id=req.id, status="INSUFFICIENT_EVIDENCE",
                                 explanation=f"Not established: {missing}", endpoints=eps,
                                 identity_state=identity_state, identity_evidence=identity_ev,
                                 gaps=gaps, contradictions=contradictions, assumptions=assumptions)


_GAP_PRIORITY = ["CONTRADICTION", "DEVICE_NOT_SEEN", "PORTS_NOT_VISIBLE", "LABEL_ILLEGIBLE",
                 "PORT_NOT_FOUND", "INSERTION_UNCLEAR", "GROUNDING_MISSING", "CABLE_CONTINUITY"]


def select_gap(assessments: list[RequirementAssessment], exhausted: set[str]) -> Gap | None:
    """Pick the most fundamental open gap that has not exhausted its attempts."""
    cands = [g for a in assessments if a.status == "INSUFFICIENT_EVIDENCE" for g in a.gaps
             if g.key not in exhausted]
    if not cands:
        return None
    return min(cands, key=lambda g: (_GAP_PRIORITY.index(g.code), g.requirement_id, g.endpoint_index or 0))
