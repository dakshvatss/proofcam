"""Deterministic verification policy.

The model never sets a verdict. This module derives VERIFIED / VIOLATED / INSUFFICIENT_EVIDENCE
from per-image claims, accumulated over all photos of the CURRENT installation configuration
(order-independent: the result depends only on the set of observations, not their sequence):

  Port identity      : a port is the spec port if, in that image, its own printed label is 'legible' and
                       matches ('direct_label'); or - only if the requirement opts in with
                       port_identity="label_or_layout" - if its label is hidden but legible neighbouring
                       labels sit at the exact positions the device's declared port_rows predict
                       ('layout_inference', see infer_port_identity). Inference is disclosed as an
                       assumption and never establishes a violation.
  Endpoint support   : a usable image where the spec device is identified with 'clear' certainty, the
                       port is identified, a cable is inserted with 'clear' visibility, the plug colour
                       matches (or the plug is colourless/unknown and a cable of the required colour
                       visibly belongs to that port in the same image), and (by default) a SAM mask of
                       the required cable reaches the port region.
  Endpoint violation : same identification by DIRECT label, and the port is clearly empty or clearly
                       holds a plug of a different stated colour; or, only when the spec asserts the
                       cable is unique, the required cable is clearly in another legibly labelled port.
  Contradiction      : support and violation for the same endpoint -> never resolved silently.
  Cable identity     : ONE image in which a cable of the required colour is fully traced between a port
                       identified (as above) as endpoint 1 and a port identified as endpoint 2, each with
                       a cable inserted (SAM-grounded by default). That image need not be the one that
                       supports the endpoints: identity and endpoint support are separate facts, joined
                       through port identity under the static-installation assumption. Or: an explicit
                       spec assertion (disclosed). Similar cables in different images are never joined.
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
    PortIdentityBasis,
    RequirementAssessment,
)
from .observation import Box1000, ObservationExtraction, PortObservation, SeenDevice
from .spec import ConnectionRequirement, DeviceSpec, EndpointSpec, InspectionSpec, normalize_label

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
    # Kept distinct from white: a beige plug must not satisfy a "white cable" requirement or vice versa.
    "beige": "beige", "cream": "beige", "tan": "beige", "khaki": "beige", "ivory": "beige",
}

# Layout inference geometry (Muse 0-1000 boxes). Ports are in one row if their vertical extents overlap by
# at least this fraction of the smaller box; neighbour spacing may vary at most by this ratio, so that a
# port Muse failed to report (which would double one spacing) breaks the inference instead of shifting it.
ROW_MIN_Y_OVERLAP = 0.5
MAX_PITCH_RATIO = 1.5


def base_color(c: str | None) -> str | None:
    """Map a free-text colour to one base colour; None if unknown or ambiguous ('blue/white')."""
    if not c:
        return None
    found = {_COLOR_WORDS[w] for w in re.findall(r"[a-z]+", c.lower()) if w in _COLOR_WORDS}
    return found.pop() if len(found) == 1 else None


def _legible_labels(p: PortObservation) -> set[str]:
    if p.label_legibility != "legible" or not p.label_read:
        return set()
    out = {normalize_label(p.label_read)}
    if p.label_group:
        out.add(normalize_label(f"{p.label_group} {p.label_read}"))
    return out


def label_matches(p: PortObservation, e: EndpointSpec) -> bool:
    return bool(_legible_labels(p) & e.accepted_labels())


def _cx(b: Box1000) -> float:
    return (b.x1 + b.x2) / 2


def _same_row(a: Box1000, b: Box1000) -> bool:
    overlap = min(a.y2, b.y2) - max(a.y1, b.y1)
    return overlap >= ROW_MIN_Y_OVERLAP * min(a.y2 - a.y1, b.y2 - b.y1)


def infer_port_identity(ext: ObservationExtraction, device_ref: str, p: PortObservation, e: EndpointSpec,
                        dev: DeviceSpec) -> str | None:
    """Identify a port whose own label is NOT legible from its legible neighbours and the declared layout.

    Returns an audit note describing the inference, or None. All of these must hold in this one image:
      - the device declares a port row containing the target label exactly once;
      - every port Muse reported on this device has a box (an unboxed port could sit anywhere in the row);
      - no port on the device is legibly labelled as the target;
      - every legibly labelled port of that row lies at exactly the offset the layout predicts;
      - two anchors are legible: both immediate neighbours for an interior port, or the next two
        inward ports for a row-end port;
      - the spacing across target and anchors is regular (ratio <= MAX_PITCH_RATIO), so a missed port
        between them cannot silently shift the identification.
    """
    if p.box is None or _legible_labels(p):
        return None
    dev_ports = [q for q in ext.ports if q.device_ref == device_ref]
    if any(q.box is None for q in dev_ports):
        return None
    accepted = e.accepted_labels()
    if any(_legible_labels(q) & accepted for q in dev_ports):
        return None
    for row in dev.port_rows:
        norm = [normalize_label(x) for x in row]
        hits = [i for i, n in enumerate(norm) if n in accepted]
        if len(norm) < 3 or len(hits) != 1:
            continue
        i = hits[0]
        row_ports = sorted((q for q in dev_ports if _same_row(q.box, p.box)), key=lambda q: _cx(q.box))
        k = next(j for j, q in enumerate(row_ports) if q.ref == p.ref)
        placed: dict[int, str] = {}
        consistent = True
        for j, q in enumerate(row_ports):
            labs = _legible_labels(q) & set(norm)
            if not labs:
                continue
            lab = labs.pop()
            if j != k + norm.index(lab) - i:
                consistent = False
                break
            placed[j] = row[norm.index(lab)]
        if not consistent:
            continue
        if 0 < i < len(norm) - 1:
            anchors, chain = [k - 1, k + 1], [k - 1, k, k + 1]
        elif i == 0:
            anchors, chain = [k + 1, k + 2], [k, k + 1, k + 2]
        else:
            anchors, chain = [k - 1, k - 2], [k - 2, k - 1, k]
        if not all(a in placed for a in anchors):
            continue
        cs = [_cx(row_ports[j].box) for j in chain]
        d1, d2 = cs[1] - cs[0], cs[2] - cs[1]
        if min(d1, d2) <= 0 or max(d1, d2) / min(d1, d2) > MAX_PITCH_RATIO:
            continue
        return (f"own label not readable; identified as '{row[i]}' from legible neighbours "
                + ", ".join(f"'{placed[a]}' ({row_ports[a].ref})" for a in sorted(anchors))
                + f" at the positions declared in port row {row}")
    return None


def identify_port(ext: ObservationExtraction, d: SeenDevice, p: PortObservation, e: EndpointSpec,
                  dev: DeviceSpec) -> tuple[PortIdentityBasis | None, str | None]:
    if label_matches(p, e):
        return "direct_label", None
    note = infer_port_identity(ext, d.ref, p, e, dev)
    return ("layout_inference", note) if note else (None, None)


def _plug_color(ext: ObservationExtraction, p: PortObservation, want: str | None) -> tuple[str | None, str]:
    """Base colour of what is in the port, for SUPPORT only.

    The plug's own stated colour wins. If it has none we can map (e.g. a clear 'transparent' RJ45 plug),
    a cable of the required colour that Muse says visibly belongs to this port in the same image counts.
    """
    got = base_color(p.plug_color)
    if got or not want:
        return got, "plug"
    if any(p.ref in c.connected_port_refs and base_color(c.color) == want for c in ext.cables):
        return want, "cable"
    return None, "plug"


def _port_desc(p: PortObservation) -> str:
    lab = f"{p.label_group + ' ' if p.label_group else ''}{p.label_read or '?'}"
    return (f"port {p.ref} '{lab}' [{p.label_legibility}] ({p.occupancy}, plug={p.plug_color or 'n/a'}, "
            f"visibility={p.insertion_visibility})")


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
    allow_inference = req.port_identity == "label_or_layout"
    support: list[EvidenceItem] = []
    weak: list[EvidenceItem] = []
    conflicts: list[EvidenceItem] = []
    unclear_matches: list[EvidenceItem] = []
    inferred_only: list[EvidenceItem] = []
    hidden_label_plugs: list[EvidenceItem] = []  # matching plug in a port whose label could not be read
    illegible_ports = 0
    ports_seen = 0
    sides: set[str] = set()

    hits: list[tuple[ObservationRecord, SeenDevice]] = list(_device_hits(obs, e.device_id))
    for o, d in hits:
        ext = o.extraction
        sides.add(d.visible_side)
        for p in ext.ports:  # type: ignore[union-attr]
            if p.device_ref != d.ref:
                continue
            ports_seen += 1
            if p.label_legibility in ("partially_legible", "illegible"):
                illegible_ports += 1
            basis, how = identify_port(ext, d, p, e, dev)
            item = EvidenceItem(seq=o.seq, image_id=o.image_id, port_ref=p.ref, device_ref=d.ref,
                                claim=f"{dev.name} {_port_desc(p)}" + (f" — {how}" if how else ""),
                                grounding=o.port_links.get(f"{p.ref}|{concept}"), port_basis=basis)
            clear = p.insertion_visibility == "clear"
            stated = base_color(p.plug_color)
            got, via = _plug_color(ext, p, want)
            colour_ok = clear and p.occupancy == "cable_inserted" and got is not None and got == want
            if colour_ok and via == "cable":
                item = item.model_copy(update={"claim": item.claim + f" -> plug colourless; {want} cable "
                                                                     "visibly belongs to this port"})
            grounded = item.grounding is not None and item.grounding.corroborated
            if basis == "direct_label":
                if clear and p.occupancy == "empty":
                    conflicts.append(item.model_copy(update={"claim": item.claim + " -> target port is empty"}))
                elif clear and p.occupancy == "cable_inserted" and stated and want and stated != want:
                    conflicts.append(item.model_copy(update={
                        "claim": item.claim + f" -> holds a {stated} plug, not {want}"}))
                elif colour_ok:
                    (support if grounded or not require_grounding else weak).append(item)
                else:
                    unclear_matches.append(item)
            elif basis == "layout_inference":
                if colour_ok and allow_inference:
                    (support if grounded or not require_grounding else weak).append(item)
                else:
                    # Not permitted, or not a positive observation: kept for audit and guidance only.
                    # Inference never establishes a violation.
                    inferred_only.append(item)
            else:
                if colour_ok and not _legible_labels(p):
                    hidden_label_plugs.append(item)
                if (req.cable_identity == "unique_in_installation" and p.label_legibility == "legible"
                        and clear and p.occupancy == "cable_inserted" and stated and stated == want):
                    conflicts.append(item.model_copy(update={
                        "claim": item.claim + f" -> the (spec-unique) {want} cable is in the wrong port"}))

    def gap(code, fact, **ctx) -> Gap:
        return Gap(requirement_id=req.id, code=code, endpoint_index=idx, target=target,
                   missing_fact=fact, context={"device_id": dev.id, "device": dev.name,
                                               "device_description": dev.description,
                                               "port_label": e.port_label, **ctx})

    def result(state, g=None, **kw) -> EndpointAssessment:
        return EndpointAssessment(index=idx, device_id=e.device_id, port_label=e.port_label, state=state,
                                  inferred_only=inferred_only, gap=g, **kw)

    claimed_support = support + weak
    if claimed_support and conflicts:
        return result("contradicted", gap("CONTRADICTION",
                                          f"Observations of {target} conflict; a clear, close view is needed. "
                                          "If the equipment was physically changed between photos, the change "
                                          "must be declared so earlier photos stop counting.",
                                          images=sorted({x.image_id for x in claimed_support + conflicts})),
                      support=claimed_support, conflicts=conflicts)
    if support:
        return result("established", support=support)
    if conflicts:
        return result("violated", conflicts=conflicts)
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
    elif inferred_only or hidden_label_plugs:
        layout_ok = any(x.port_basis == "layout_inference" for x in inferred_only)
        fact = (f"A {req.cable_color} plug was seen in a {dev.name} port whose own printed label is not "
                f"readable (likely hidden by the plug), so it is not established that this is {e.port_label}.")
        if layout_ok:
            fact += (" Neighbouring labels place it at the declared position of "
                     f"{e.port_label}, but this requirement accepts only a directly readable label.")
        g = gap("LABEL_ILLEGIBLE", fact, sides_seen=sorted(sides), label_hidden_by_plug=True,
                layout_inference_available=layout_ok,
                candidate_ports=[f"[{x.image_id}] {x.claim}" for x in inferred_only + hidden_label_plugs][:4])
    elif illegible_ports:
        g = gap("LABEL_ILLEGIBLE",
                f"Ports on the {dev.name} were seen, but labels were not legible enough to find {e.port_label}.",
                sides_seen=sorted(sides))
    else:
        g = gap("PORT_NOT_FOUND", f"No observed port on the {dev.name} was legibly labelled {e.port_label}.",
                sides_seen=sorted(sides))
    return result("unknown", g)


def identity_evidence(spec: InspectionSpec, req: ConnectionRequirement, obs: list[ObservationRecord],
                      require_grounding: bool) -> tuple[list[EvidenceItem], list[str]]:
    """Single-image proofs that one cable of the required colour runs between the two spec ports.

    Independent of where endpoint support came from; each item names its image and both port identities.
    Also returns near misses (a matching cable fully traced between the two devices whose ports could not
    be identified/grounded in that photo) for guidance and the report; they are never evidence.
    """
    want = base_color(req.cable_color)
    concept = req.cable_concept()
    allow_inference = req.port_identity == "label_or_layout"
    out: list[EvidenceItem] = []
    near: list[str] = []
    for o in obs:
        if not o.usable:
            continue
        ext = o.extraction
        devs = {d.ref: d for d in ext.devices if d.identification_certainty == "clear"}  # type: ignore[union-attr]
        ports = {p.ref: p for p in ext.ports}  # type: ignore[union-attr]
        for c in ext.cables:  # type: ignore[union-attr]
            if c.path_visibility != "fully_traced" or base_color(c.color) != want:
                continue
            ends, why, attached = [], [], []
            for e in req.endpoints:
                hit, reason, seen = None, "", False
                for pr in c.connected_port_refs:
                    p, d = ports[pr], devs.get(ports[pr].device_ref)
                    if d is None or d.spec_device_id != e.device_id or p.occupancy != "cable_inserted":
                        continue
                    seen = True
                    if base_color(p.plug_color) not in (None, want):
                        reason = f"{pr} holds a {p.plug_color} plug"
                        continue
                    link = o.port_links.get(f"{pr}|{concept}")
                    if require_grounding and not (link and link.corroborated):
                        reason = f"{pr} is not SAM-grounded"
                        continue
                    basis, _ = identify_port(ext, d, p, e, spec.device(e.device_id))
                    if basis == "direct_label" or (basis == "layout_inference" and allow_inference):
                        hit = (p, basis)
                        break
                    reason = (f"{pr} could not be identified as {e.port_label} in this photo "
                              f"(label {p.label_legibility}"
                              + ("; layout inference not permitted" if basis == "layout_inference" else "") + ")")
                ends.append(hit)
                why.append(reason)
                attached.append(seen)
            if all(ends):
                desc = [f"{spec.device(e.device_id).name} {e.port_label} = {p.ref} ({basis})"
                        for e, (p, basis) in zip(req.endpoints, ends)]
                out.append(EvidenceItem(
                    seq=o.seq, image_id=o.image_id,
                    port_basis="layout_inference" if any(b == "layout_inference" for _, b in ends)
                    else "direct_label",
                    claim=f"{c.color} cable {c.ref} traced continuously between " + " and ".join(desc)
                          + (", SAM-grounded at both ports" if require_grounding else "")))
            elif all(attached):
                near.append(f"[photo {o.seq} · {o.image_id}] {c.color} cable {c.ref} is fully traced between the "
                            "two devices, but " + "; ".join(w for w, h in zip(why, ends) if not h))
    return out, near


def _photos(items: list[EvidenceItem]) -> str:
    return ", ".join(f"photo {s}" for s in sorted({x.seq for x in items})) or "none"


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
        why = "; ".join(f"[photo {c.seq}] {c.claim}" for ep in violated for c in ep.conflicts)
        return RequirementAssessment(requirement_id=req.id, status="VIOLATED",
                                     explanation=f"Clearly observed: {why}.", endpoints=eps,
                                     identity_state=identity_state, gaps=gaps,
                                     contradictions=contradictions)

    for ep in eps:
        inferred = [s for s in ep.support if s.port_basis == "layout_inference"]
        if inferred:
            assumptions.append(f"{spec.device(ep.device_id).name} {ep.port_label} was identified by layout "
                               f"inference in {_photos(inferred)} (its own label was not readable); this relies "
                               "on the spec-declared port order.")
    both = all(ep.state == "established" for ep in eps)
    if req.cable_identity == "unique_in_installation":
        if both:
            identity_state = "assumed_by_spec"
            assumptions.append(f"Spec asserts exactly one {req.cable_color} {req.cable_type} exists, so the "
                               "two endpoint observations are treated as the same cable.")
    else:
        identity_ev, near = identity_evidence(spec, req, obs, require_grounding)
        identity_state = "established" if identity_ev else "unknown"
        if any(x.port_basis == "layout_inference" for x in identity_ev):
            assumptions.append("Cable-trace port identity relies on layout inference in "
                               f"{_photos(identity_ev)}.")
        if both and not identity_ev:
            gaps.append(Gap(requirement_id=req.id, code="CABLE_CONTINUITY", endpoint_index=None,
                            target=f"the {req.cable_color} cable run between both endpoints",
                            missing_fact=("Both ends show a matching plug, but no single photo shows the "
                                          "same cable running continuously between the two identified ports."
                                          + (" Near miss: " + " | ".join(near[:2]) if near else "")),
                            context={"endpoints": [f"{spec.device(x.device_id).name} {x.port_label}"
                                                   for x in req.endpoints], "near_misses": near[:3]}))
    if both and identity_state in ("established", "assumed_by_spec"):
        where = "; ".join(f"{spec.device(ep.device_id).name} {ep.port_label} from {_photos(ep.support)}"
                          for ep in eps)
        return RequirementAssessment(
            requirement_id=req.id, status="VERIFIED",
            explanation="Both endpoints observed with identified ports, clear insertion and matching colour"
                        + (", SAM-grounded" if require_grounding else "") + f" ({where})"
                        + (f"; cable identity traced in {_photos(identity_ev)}." if identity_state == "established"
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


def select_gap(assessments: list[RequirementAssessment], exhausted: set[str],
               in_view: set[str] | None = None) -> Gap | None:
    """Pick the open gap to request next.

    Contradictions first. Then gaps on a device visible in the latest usable photo (the technician is
    already there), then the most fundamental gap type. Gaps that exhausted their attempts are skipped.
    """
    cands = [g for a in assessments if a.status == "INSUFFICIENT_EVIDENCE" for g in a.gaps
             if g.key not in exhausted]
    if not cands:
        return None
    seen = in_view or set()
    return min(cands, key=lambda g: (g.code != "CONTRADICTION", g.context.get("device_id") not in seen,
                                     _GAP_PRIORITY.index(g.code), g.requirement_id, g.endpoint_index or 0))
