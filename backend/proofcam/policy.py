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
  Device identity    : per photo, by Muse's match to the spec description. A photo in which more than one
                       device claims the same spec id is not used for that device (ambiguous). Recognition
                       across photos is not proof of the same physical unit (disclosed in reports).
  Colour             : three-way (compare_color): MATCH supports, CLEAR MISMATCH may violate, UNCERTAIN
                       (near colours, unknown words, several colours, see-through plugs described with a
                       colour, plug vs attached cable disagreeing in one photo) does neither.
  Endpoint support   : a usable image where the spec device is identified with 'clear' certainty, the
                       port is identified, a cable is inserted with 'clear' visibility, the plug colour
                       matches (or the plug is colourless/see-through and a cable of the required colour
                       visibly belongs to that port in the same image - then SAM grounding at the port is
                       required even in ablation), and (by default) a SAM mask of the required cable
                       reaches the port region.
  Endpoint violation : same identification by DIRECT label, and the port is clearly empty or clearly
                       holds a plug of a clearly different stated colour; or, only when the spec asserts the
                       cable is unique, the required cable is clearly in another legibly labelled port.
  Contradiction      : support and violation for the same endpoint, or a qualifying trace of an endpoint's
                       cable to a different (legibly labelled) port opposing a proof of identity -> never
                       resolved silently.
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
from collections import Counter
from typing import Literal

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
    # Unlisted words (teal, cyan, charcoal, ...) map to nothing: compare_color() treats them as uncertain.
}

# Words saying the plug itself is see-through: its apparent colour comes from the cable, boot or background.
_TRANSPARENT_WORDS = {"clear", "transparent", "translucent", "colorless", "colourless"}

# Base colours that the same physical plug is plausibly described as (lighting, wording, camera white
# balance). Between such neighbours a description is UNCERTAIN: it neither supports nor violates.
_NEAR = {frozenset(p) for p in [
    ("white", "beige"), ("white", "gray"), ("beige", "gray"), ("black", "gray"), ("beige", "yellow"),
    ("beige", "brown"), ("blue", "purple"), ("green", "yellow"),
    ("red", "pink"), ("red", "orange"), ("red", "brown"), ("orange", "yellow"), ("orange", "brown"),
    ("pink", "purple"),
]}

ColorMatch = Literal["match", "mismatch", "uncertain"]

# Layout inference geometry (Muse 0-1000 boxes). Ports are in one row if their vertical extents overlap by
# at least this fraction of the smaller box; neighbour spacing may vary at most by this ratio, so that a
# port Muse failed to report (which would double one spacing) breaks the inference instead of shifting it.
ROW_MIN_Y_OVERLAP = 0.5
MAX_PITCH_RATIO = 1.5


def _words(c: str | None) -> list[str]:
    return re.findall(r"[a-z]+", c.lower()) if c else []


def base_color(c: str | None) -> str | None:
    """Map a free-text colour to one base colour; None if unknown or ambiguous ('blue/white')."""
    found = {_COLOR_WORDS[w] for w in _words(c) if w in _COLOR_WORDS}
    return found.pop() if len(found) == 1 else None


def is_colourless(c: str | None) -> bool:
    """No usable plug colour: none stated, a see-through plug, or no recognisable colour word."""
    words = _words(c)
    return not words or any(w in _TRANSPARENT_WORDS for w in words) or not any(w in _COLOR_WORDS for w in words)


def compare_color(c: str | None, want: str | None) -> ColorMatch:
    """Three-way comparison of a free-text colour with a required base colour.

    match     - exactly one recognised base colour, equal to the requirement;
    mismatch  - exactly one recognised base colour, clearly different (not a near neighbour), not see-through;
    uncertain - everything else: unknown words, several colours, near neighbours ('dark gray' vs black),
                or a see-through plug described with another colour ('translucent white').
    Only 'match' can support and only 'mismatch' can violate.
    """
    found = {_COLOR_WORDS[w] for w in _words(c) if w in _COLOR_WORDS}
    if not want or len(found) != 1:
        return "uncertain"
    got = found.pop()
    if got == want:
        return "match"
    if any(w in _TRANSPARENT_WORDS for w in _words(c)) or frozenset((got, want)) in _NEAR:
        return "uncertain"
    return "mismatch"


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


def plug_colour_status(ext: ObservationExtraction, p: PortObservation,
                       want: str | None) -> tuple[ColorMatch, Literal["plug", "cable", "disagreement"]]:
    """Colour of what is in the port, judged against the required base colour, within ONE image.

    The plug's own stated colour decides when it is a clear match or mismatch. A colourless or see-through plug
    takes the colour of a cable that Muse says visibly belongs to this port in the same image ('cable'; support
    then additionally requires SAM grounding at the port, see assess_endpoint). A plug stated as a clearly
    different colour while a linked cable is (or may be) the required colour is a disagreement inside one photo:
    uncertain, never a violation.
    """
    own = compare_color(p.plug_color, want)
    linked = [compare_color(c.color, want) for c in ext.cables if p.ref in c.connected_port_refs]
    if own == "match":
        return "match", "plug"
    if own == "mismatch":
        return ("uncertain", "disagreement") if any(x != "mismatch" for x in linked) else ("mismatch", "plug")
    if is_colourless(p.plug_color) and "match" in linked:
        return "match", "cable"
    return "uncertain", "plug"


def _port_desc(p: PortObservation) -> str:
    lab = f"{p.label_group + ' ' if p.label_group else ''}{p.label_read or '?'}"
    return (f"port {p.ref} '{lab}' [{p.label_legibility}] ({p.occupancy}, plug={p.plug_color or 'n/a'}, "
            f"visibility={p.insertion_visibility})")


def ambiguous_device_ids(ext: ObservationExtraction) -> set[str]:
    """Spec ids claimed by more than one device in this photo (any certainty). Which device is the specified one
    is then unknown, so that photo is not used for that spec device at all (neither support nor violation)."""
    counts = Counter(d.spec_device_id for d in ext.devices if d.spec_device_id)
    return {i for i, n in counts.items() if n > 1}


def ambiguous_photos(obs: list[ObservationRecord], device_id: str) -> list[int]:
    return [o.seq for o in obs if o.usable and device_id in ambiguous_device_ids(o.extraction)]  # type: ignore[arg-type]


def _device_hits(obs: list[ObservationRecord], device_id: str, certainty: str = "clear"):
    for o in obs:
        if not o.usable or device_id in ambiguous_device_ids(o.extraction):  # type: ignore[arg-type]
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
    colour_uncertain: list[EvidenceItem] = []  # clear insertion, stated colour neither matches nor clearly differs
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
            inserted = p.occupancy == "cable_inserted"
            status, via = plug_colour_status(ext, p, want)
            colour_ok = clear and inserted and status == "match"
            if colour_ok and via == "cable":
                item = item.model_copy(update={"claim": item.claim + f" -> plug colourless; {want} cable "
                                                                     "visibly belongs to this port"})
            grounded = item.grounding is not None and item.grounding.corroborated
            # A colourless plug borrows the cable's colour only through the Muse link; that association must be
            # SAM-grounded even when grounding is otherwise not required (ablation runs).
            strong = grounded or (not require_grounding and via == "plug")
            if basis == "direct_label":
                if clear and p.occupancy == "empty":
                    conflicts.append(item.model_copy(update={"claim": item.claim + " -> target port is empty"}))
                elif clear and inserted and status == "mismatch":
                    conflicts.append(item.model_copy(update={
                        "claim": item.claim + f" -> holds a {base_color(p.plug_color)} plug, not {want}"}))
                elif colour_ok:
                    (support if strong else weak).append(item)
                elif clear and inserted and p.plug_color and status == "uncertain":
                    note = (" -> plug colour disagrees with the cable attached to it in this photo"
                            if via == "disagreement" else
                            f" -> stated plug colour '{p.plug_color}' is not clearly {want} nor clearly another "
                            "colour")
                    colour_uncertain.append(item.model_copy(update={"claim": item.claim + note}))
                else:
                    unclear_matches.append(item)
            elif basis == "layout_inference":
                if colour_ok and allow_inference:
                    (support if strong else weak).append(item)
                else:
                    # Not permitted, or not a positive observation: kept for audit and guidance only.
                    # Inference never establishes a violation.
                    inferred_only.append(item)
            else:
                if colour_ok and not _legible_labels(p):
                    hidden_label_plugs.append(item)
                if (req.cable_identity == "unique_in_installation" and p.label_legibility == "legible"
                        and clear and inserted and status == "match" and via == "plug"):
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
                                          f"Observations of {target} conflict ({_photos(claimed_support)} vs "
                                          f"{_photos(conflicts)}). Further photos of an unchanged installation "
                                          "cannot remove this conflict, because every photo keeps counting; the "
                                          "installation needs review. If the equipment was physically changed "
                                          "between photos, the change must be declared so earlier photos stop "
                                          "counting.",
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
    elif colour_uncertain:
        g = gap("INSERTION_UNCLEAR",
                f"{target} holds a plug whose colour could not be established as {req.cable_color} (nor clearly as "
                "another colour); a closer view in good light of the plug and the cable leaving it is needed.",
                colour_ambiguous=True,
                observed=[f"[{x.image_id}] {x.claim}" for x in colour_uncertain][:3])
    elif unclear_matches:
        g = gap("INSERTION_UNCLEAR",
                f"{target} was found, but whether a {req.cable_color} plug is clearly inserted is not visible.")
    elif not hits:
        uncertain = any(True for _ in _device_hits(obs, e.device_id, "uncertain"))
        ambiguous = ambiguous_photos(obs, e.device_id)
        g = gap("DEVICE_NOT_SEEN",
                f"The {dev.name} has not been identified with certainty in any photo."
                + (f" In {_seqs(ambiguous)} more than one device was identified as the {dev.name}, so which one "
                   "is the specified device is ambiguous and those photos are not used for it." if ambiguous else ""),
                seen_uncertain=uncertain, ambiguous_photos=ambiguous)
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
                      require_grounding: bool) -> tuple[list[EvidenceItem], list[str], list[EvidenceItem]]:
    """Single-image proofs that one cable of the required colour runs between the two spec ports.

    Independent of where endpoint support came from; each item names its image and both port identities.
    Also returns near misses (a matching cable fully traced between the two devices whose ports could not
    be identified/grounded in that photo) for guidance and the report; they are never evidence.

    And returns conflicting traces: a cable meeting every condition of a proof (fully traced, required colour,
    plugs inserted and of matching colour, SAM-grounded) that runs from a port identified as one spec endpoint to
    a port on the other spec device whose own label is legibly a DIFFERENT port. Under the static-installation
    assumption a port holds one plug and a plug one cable, so such a trace contradicts any proof that the same
    endpoint's cable reaches the spec port. Identified by direct label only on the conflicting side (inference
    never establishes negative evidence). Similar-looking cables in different photos are never joined: the
    conflict is about the cable in one identified port, not about cable appearance.
    """
    want = base_color(req.cable_color)
    concept = req.cable_concept()
    allow_inference = req.port_identity == "label_or_layout"
    out: list[EvidenceItem] = []
    near: list[str] = []
    conflicts: list[EvidenceItem] = []
    for o in obs:
        if not o.usable:
            continue
        ext = o.extraction
        amb = ambiguous_device_ids(ext)  # type: ignore[arg-type]
        devs = {d.ref: d for d in ext.devices  # type: ignore[union-attr]
                if d.identification_certainty == "clear" and d.spec_device_id not in amb}
        ports = {p.ref: p for p in ext.ports}  # type: ignore[union-attr]
        for c in ext.cables:  # type: ignore[union-attr]
            if c.path_visibility != "fully_traced" or compare_color(c.color, want) != "match":
                continue
            ends, why, attached, elsewhere = [], [], [], []
            for e in req.endpoints:
                hit, reason, seen, other = None, "", False, None
                for pr in c.connected_port_refs:
                    p, d = ports[pr], devs.get(ports[pr].device_ref)
                    if d is None or d.spec_device_id != e.device_id or p.occupancy != "cable_inserted":
                        continue
                    seen = True
                    if plug_colour_status(ext, p, want)[0] != "match":  # type: ignore[arg-type]
                        reason = f"{pr} holds a {p.plug_color} plug"
                        continue
                    link = o.port_links.get(f"{pr}|{concept}")
                    if require_grounding and not (link and link.corroborated):
                        reason = f"{pr} is not SAM-grounded"
                        continue
                    basis, _ = identify_port(ext, d, p, e, spec.device(e.device_id))  # type: ignore[arg-type]
                    if basis == "direct_label" or (basis == "layout_inference" and allow_inference):
                        hit = (p, basis)
                        break
                    if _legible_labels(p) and not label_matches(p, e):
                        other = p  # qualified plug at a legibly DIFFERENT port of this spec device
                    reason = (f"{pr} could not be identified as {e.port_label} in this photo "
                              f"(label {p.label_legibility}"
                              + ("; layout inference not permitted" if basis == "layout_inference" else "") + ")")
                ends.append(hit)
                why.append(reason)
                attached.append(seen)
                elsewhere.append(other)
            for i in (0, 1):
                j = 1 - i
                if ends[i] and elsewhere[j] is not None:
                    (pa, basis_a), pb = ends[i], elsewhere[j]
                    ea, eb = req.endpoints[i], req.endpoints[j]
                    conflicts.append(EvidenceItem(
                        seq=o.seq, image_id=o.image_id, port_ref=pa.ref, port_basis=basis_a,
                        claim=f"{c.color} cable {c.ref} traced from {spec.device(ea.device_id).name} {ea.port_label} "
                              f"= {pa.ref} ({basis_a}) to {spec.device(eb.device_id).name} port "
                              f"'{pb.label_read}' ({pb.ref}), not {eb.port_label}"
                              + (", SAM-grounded at both ports" if require_grounding else "")))
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
    return out, near, conflicts


def _seqs(seqs: list[int]) -> str:
    return ", ".join(f"photo {s}" for s in sorted(set(seqs))) or "no photo"


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

    ambiguity = _ambiguity_note(spec, req, obs)

    violated = [ep for ep in eps if ep.state == "violated"]
    if violated:
        why = "; ".join(f"[photo {c.seq}] {c.claim}" for ep in violated for c in ep.conflicts)
        return RequirementAssessment(requirement_id=req.id, status="VIOLATED",
                                     explanation=f"Clearly observed: {why}." + ambiguity, endpoints=eps,
                                     identity_state=identity_state, gaps=gaps,
                                     contradictions=contradictions)

    for ep in eps:
        inferred = [s for s in ep.support if s.port_basis == "layout_inference"]
        if inferred:
            assumptions.append(f"{spec.device(ep.device_id).name} {ep.port_label} was identified by layout "
                               f"inference in {_photos(inferred)} (its own label was not readable); this relies "
                               "on the spec-declared port order.")
    both = all(ep.state == "established" for ep in eps)
    traced, near, trace_conflicts = identity_evidence(spec, req, obs, require_grounding)
    unique = req.cable_identity == "unique_in_installation"
    # Opposing traces: a proof that the endpoint's cable reaches the spec port and a qualifying trace of the same
    # endpoint's cable to another port (or, when the spec asserts the cable is unique, any such trace while both
    # endpoints are supported). Never resolved silently: the identity becomes a visible contradiction.
    contested = bool(trace_conflicts) and (both if unique else bool(traced))
    if trace_conflicts and not contested:
        near = near + [f"[photo {x.seq} · {x.image_id}] conflicting trace (not counted as evidence): {x.claim}"
                       for x in trace_conflicts]
    if unique:
        if both and not contested:
            identity_state = "assumed_by_spec"
            assumptions.append(f"Spec asserts exactly one {req.cable_color} {req.cable_type} exists, so the "
                               "two endpoint observations are treated as the same cable.")
    else:
        identity_ev = traced
        identity_state = "established" if identity_ev and not contested else "unknown"
        if any(x.port_basis == "layout_inference" for x in identity_ev):
            assumptions.append("Cable-trace port identity relies on layout inference in "
                               f"{_photos(identity_ev)}.")
    if contested:
        opposing = (traced if not unique else []) + trace_conflicts
        contradictions.append("cable identity: " + "; ".join(f"[{x.image_id}] {x.claim}" for x in opposing))
        gaps.append(Gap(requirement_id=req.id, code="CONTRADICTION", endpoint_index=None,
                        target=f"the {req.cable_color} cable run between both endpoints",
                        missing_fact=("Photos disagree about where the "
                                      f"{req.cable_color} cable runs: {_photos(opposing)} trace it to different "
                                      "ports. An unchanged installation has one cable per plug, so this conflict "
                                      "cannot be resolved by choosing one photo. If the equipment was physically "
                                      "changed between photos, the change must be declared so earlier photos stop "
                                      "counting."),
                        context={"images": sorted({x.image_id for x in opposing}),
                                 "trace_conflicts": [f"[{x.image_id}] {x.claim}" for x in trace_conflicts][:3]}))
    elif not unique:
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
                           else "; cable identity relies on a spec assertion.") + ambiguity,
            endpoints=eps, identity_state=identity_state, identity_evidence=identity_ev,
            assumptions=assumptions)

    missing = "; ".join(g.missing_fact for g in gaps)
    if trace_conflicts and not contested and not any(g.code == "CABLE_CONTINUITY" for g in gaps):
        missing += ". Conflicting trace (not counted as evidence): " + "; ".join(
            f"[photo {x.seq}] {x.claim}" for x in trace_conflicts[:2])
    if ambiguity and "more than one device was identified" not in missing:
        missing += "." + ambiguity
    return RequirementAssessment(requirement_id=req.id, status="INSUFFICIENT_EVIDENCE",
                                 explanation=f"Not established: {missing}", endpoints=eps,
                                 identity_state=identity_state, identity_evidence=identity_ev,
                                 gaps=gaps, contradictions=contradictions, assumptions=assumptions)


def _ambiguity_note(spec: InspectionSpec, req: ConnectionRequirement, obs: list[ObservationRecord]) -> str:
    """Sentence naming photos not used for a spec device because several devices in them claimed its id."""
    notes = []
    for device_id in dict.fromkeys(e.device_id for e in req.endpoints):
        seqs = ambiguous_photos(obs, device_id)
        if seqs:
            notes.append(f" {_seqs(seqs).capitalize()} not used for the {spec.device(device_id).name}: more than "
                         "one device in the photo was identified as it, so which one is the specified device is "
                         "ambiguous.")
    return "".join(notes)


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
