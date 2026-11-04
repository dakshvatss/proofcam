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
  Connector family   : the requirement's connector (ethernet, hdmi, ...). A port or cable whose observed family
                       is clearly another one is never this requirement's port or cable (neither support nor
                       violation). "unclear" is consistent with any family, except that on a device which is an
                       endpoint of requirements with DIFFERENT connector families, negative evidence (wrong-port
                       plug, conflicting trace) needs the family to be observed explicitly.
  VERIFIED           : both endpoints supported AND identity established. Anything less is
                       INSUFFICIENT_EVIDENCE unless there is an uncontradicted violation.
  Flexible endpoints : (spec.PortSelector) any port in an allowed label list or label group, or - only where the
                       spec asserts it - any socket of the requirement's connector family whose shape was OBSERVED
                       (disclosed as an assumption). Unknown ports never qualify. An empty permitted port, or one
                       holding another cable, is not a violation (another permitted port may be used); only every
                       listed permitted port clearly empty is.
  Any colour         : cable_color null. Colour neither supports nor violates; port identity, insertion, SAM
                       grounding and single-image cable identity are still required.
  Overall            : over all requirements (overall_assessment): VIOLATED if any requirement is VIOLATED,
                       VERIFIED only if every requirement is VERIFIED, otherwise INSUFFICIENT_EVIDENCE.
                       Contradictions stay listed next to it.
  Single socket      : (M3.7, PortSelector.only_socket) the spec says the device has one socket of the family, so a
                       plug there in one photo and that socket clearly empty in another is a CONTRADICTION (never a
                       violation by itself).
  Muse-only claims   : a plug that met every check except SAM grounding is kept as a `candidate` on the endpoint;
                       never support. SAM's generic 'cable' fallback (grounding.py) counts as grounding but is
                       disclosed as an assumption.
  Operator statements: (OperatorDeclaration, only where the spec permits) a device claimed UNCERTAINLY in one photo
                       may be confirmed for that photo (support only; its negative evidence never violates); a cable
                       identity may be declared between two supported endpoints whose connector family Muse reported,
                       never against a contrary trace (that becomes a CONTRADICTION). Verdicts relying on either are
                       marked assurance "operator_assisted"; the three verdict states are unchanged.
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
    OperatorDeclaration,
    OverallAssessment,
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
ConnectorMatch = Literal["match", "mismatch", "unknown"]


def connector_match(observed: str | None, want: str) -> ConnectorMatch:
    """Observed connector family vs the required one. 'unclear' (or a missing value, from observations recorded
    before connector families were reported) is unknown; any other differing family, 'other' included, is a
    mismatch."""
    if observed is None or observed == "unclear":
        return "unknown"
    return "match" if observed == want else "mismatch"


def mixed_connector_devices(spec: InspectionSpec) -> set[str]:
    """Devices that are endpoints of requirements with different connector families (e.g. a console with an
    Ethernet and an HDMI requirement). On them an unknown connector family cannot tell the requirements apart."""
    fams: dict[str, set[str]] = {}
    for r in spec.requirements:
        for e in r.endpoints:
            fams.setdefault(e.device_id, set()).add(r.connector)
    return {d for d, f in fams.items() if len(f) > 1}

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


def _excluded(p: PortObservation, e: EndpointSpec) -> bool:
    return e.selector is not None and bool(
        _legible_labels(p) & {normalize_label(x) for x in e.selector.excluded_labels})


def _in_group(p: PortObservation, group: str) -> bool:
    """Legible printed text puts this port in the group: heading == group, or label == group optionally followed
    by a number ('LAN', 'LAN 3', '3' under a 'LAN' heading; never 'WAN' or 'HDMI OUT' for 'HDMI')."""
    labels = _legible_labels(p)
    if not labels:
        return False
    g = normalize_label(group)
    if p.label_group and normalize_label(p.label_group) == g:
        return True
    return any(x.startswith(g) and (len(x) == len(g) or x[len(g)].isdigit()) for x in labels)


def label_matches(p: PortObservation, e: EndpointSpec) -> bool:
    """The port's own legible printed text identifies it as endpoint e (exact label/alias, or for a flexible
    endpoint an allowed label or the allowed group, never an excluded label)."""
    labels = _legible_labels(p)
    if e.selector is None:
        return bool(labels & e.accepted_labels())
    if not labels or _excluded(p, e):
        return False
    return bool(labels & e.accepted_labels()) or bool(e.selector.allowed_group and _in_group(p, e.selector.allowed_group))


def other_port(p: PortObservation, e: EndpointSpec) -> bool:
    """The port is positively NOT endpoint e: its printed label is legible and rules it out. Used only for negative
    evidence. A port that a flexible endpoint may accept by socket shape is never ruled out by its label, unless
    the label is explicitly excluded."""
    if not _legible_labels(p) or label_matches(p, e):
        return False
    if e.selector is None or _excluded(p, e):
        return True
    return not e.selector.any_socket_of_connector


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
                  dev: DeviceSpec, connector: str = "ethernet") -> tuple[PortIdentityBasis | None, str | None]:
    if label_matches(p, e):
        return "direct_label", None
    if e.selector is not None:
        sel = e.selector
        # Shape identification: only where the spec accepts every socket of this family on the device, only for an
        # EXPLICITLY observed matching shape, and never for a port whose legible label contradicts the selector.
        label_rules = bool(sel.allowed_labels or sel.allowed_group)
        if (sel.any_socket_of_connector and connector_match(p.connector_type, connector) == "match"
                and not _excluded(p, e) and not (label_rules and _legible_labels(p))):
            return "connector_shape", (f"identified by its observed {connector} socket shape (the spec accepts any "
                                       f"{connector} socket on the {dev.name}), not by a printed label")
        return None, None
    note = infer_port_identity(ext, d.ref, p, e, dev)
    return ("layout_inference", note) if note else (None, None)


def plug_colour_status(ext: ObservationExtraction, p: PortObservation, want: str | None,
                       connector: str = "ethernet", any_colour: bool = False
                       ) -> tuple[ColorMatch, Literal["plug", "cable", "disagreement"]]:
    """Colour of what is in the port, judged against the required base colour, within ONE image.

    The plug's own stated colour decides when it is a clear match or mismatch. A colourless or see-through plug
    takes the colour of a cable that Muse says visibly belongs to this port in the same image ('cable'; support
    then additionally requires SAM grounding at the port, see assess_endpoint). A plug stated as a clearly
    different colour while a linked cable is (or may be) the required colour is a disagreement inside one photo:
    uncertain, never a violation. Cables of a clearly different connector family are not considered.
    With any_colour (the requirement accepts any cable colour) colour is not a criterion: always 'match'.
    """
    if any_colour:
        return "match", "plug"
    own = compare_color(p.plug_color, want)
    linked = [compare_color(c.color, want) for c in ext.cables
              if p.ref in c.connected_port_refs and connector_match(c.connector_type, connector) != "mismatch"]
    if own == "match":
        return "match", "plug"
    if own == "mismatch":
        return ("uncertain", "disagreement") if any(x != "mismatch" for x in linked) else ("mismatch", "plug")
    if is_colourless(p.plug_color) and "match" in linked:
        return "match", "cable"
    return "uncertain", "plug"


def _label_text(p: PortObservation) -> str | None:
    """The port's legible printed text as read ('LAN 3', 'WAN'), or None."""
    if p.label_legibility != "legible" or not p.label_read:
        return None
    return f"{p.label_group} {p.label_read}" if p.label_group else p.label_read


def _port_desc(p: PortObservation) -> str:
    lab = f"{p.label_group + ' ' if p.label_group else ''}{p.label_read or '?'}"
    return (f"port {p.ref} '{lab}' [{p.label_legibility}] ({p.occupancy}, plug={p.plug_color or 'n/a'}, "
            f"visibility={p.insertion_visibility})")


def ambiguous_device_ids(ext: ObservationExtraction) -> set[str]:
    """Spec ids claimed by more than one device in this photo (any certainty). Which device is the specified one
    is then unknown, so that photo is not used for that spec device at all (neither support nor violation)."""
    counts = Counter(d.spec_device_id for d in ext.devices if d.spec_device_id)
    return {i for i, n in counts.items() if n > 1}


def _unconfirmed_port_photos(obs: list[ObservationRecord], device_id: str,
                             declared: frozenset[int] = frozenset()) -> dict[int, str]:
    """Photos (seq -> Muse's identification basis) in which a device claimed as `device_id` only with UNCERTAIN
    identification showed its ports, and which the person inspecting has not declared. Those ports are never
    evidence; this only makes the gap and the next camera request accurate (the ports were seen; the device's
    identity is what is missing)."""
    out: dict[int, str] = {}
    for o, d in _device_hits(obs, device_id, "uncertain", declared):
        if d.ports_visible or any(p.device_ref == d.ref for p in o.extraction.ports):  # type: ignore[union-attr]
            out.setdefault(o.seq, d.identification_basis[:160])
    return out


def ambiguous_photos(obs: list[ObservationRecord], device_id: str) -> list[int]:
    return [o.seq for o in obs if o.usable and device_id in ambiguous_device_ids(o.extraction)]  # type: ignore[arg-type]


def _device_hits(obs: list[ObservationRecord], device_id: str, certainty: str = "clear",
                 declared: frozenset[int] = frozenset()):
    """Devices claimed as `device_id` in usable, unambiguous photos. "clear": identified with certainty, or claimed
    UNCERTAINLY in a photo the person inspecting declared shows this device (see OperatorDeclaration). "uncertain":
    uncertain claims in photos NOT so declared. A declaration never re-labels a device Muse matched to something
    else, and never applies where two devices claim the spec id (ambiguous photos are skipped first)."""
    for o in obs:
        if not o.usable or device_id in ambiguous_device_ids(o.extraction):  # type: ignore[arg-type]
            continue
        for d in o.extraction.devices:  # type: ignore[union-attr]
            if d.spec_device_id != device_id:
                continue
            c = d.identification_certainty
            if certainty == "clear" and (c == "clear" or o.seq in declared):
                yield o, d
            elif certainty == "uncertain" and c == "uncertain" and o.seq not in declared:
                yield o, d


def device_declarations(spec: InspectionSpec, declarations: list[OperatorDeclaration] | tuple = ()
                        ) -> dict[str, frozenset[int]]:
    """device_id -> photo seqs the person inspecting declared show that device (only if the spec permits it)."""
    if not spec.allow_device_identity_declarations:
        return {}
    out: dict[str, set[int]] = {}
    for x in declarations:
        if x.kind == "device_identity" and x.device_id and x.seq is not None:
            out.setdefault(x.device_id, set()).add(x.seq)
    return {k: frozenset(v) for k, v in out.items()}


def _sam_found_nothing(o: ObservationRecord, concept: str) -> bool:
    """SAM ran the requirement's cable concept on this photo and segmented nothing at all. A recall failure of the
    concept, not a framing problem of one port."""
    g = next((x for x in o.sam if x.concept == concept), None)
    return g is not None and g.status == "ok" and not g.objects


_ONLY = "\x00only-socket"  # flexible cross-match key for a spec-declared single socket (never a printed label)


def ignores_colour(spec: InspectionSpec, req: ConnectionRequirement) -> bool:
    """Colour is not a criterion: the requirement accepts any colour, or an assisted template ignores colour."""
    return req.cable_color is None or (spec.assisted is not None and spec.assisted.ignore_cable_color)


def insertion_confirmations(spec: InspectionSpec, declarations: list[OperatorDeclaration] | tuple = ()
                            ) -> set[tuple[str, int]]:
    """(requirement id, endpoint index) pairs whose Muse-only insertion the person inspecting confirmed (assisted
    templates that permit it only)."""
    if spec.assisted is None or not spec.assisted.confirmable_insertions:
        return set()
    return {(x.requirement_id, x.endpoint_index) for x in declarations
            if x.kind == "endpoint_insertion" and x.requirement_id and x.endpoint_index is not None}


def confirmable(obs: list[ObservationRecord], req: ConnectionRequirement, items: list[EvidenceItem]
                ) -> list[EvidenceItem]:
    """Muse-only items strong enough for an operator to confirm: Muse explicitly reported the requirement's connector
    family at that port (an 'unclear' or other family never qualifies)."""
    return [x for x in items if _observed_family(obs, x) == req.connector]


def attestations(spec: InspectionSpec, declarations: list[OperatorDeclaration] | tuple = ()
                 ) -> dict[tuple[str, int], str]:
    """(requirement id, endpoint index) -> the written note, for assisted templates that allow attestations."""
    if spec.assisted is None or not spec.assisted.allow_attestations:
        return {}
    return {(x.requirement_id, x.endpoint_index): x.note for x in declarations
            if x.kind == "endpoint_attestation" and x.requirement_id and x.endpoint_index is not None and x.note}


def assess_endpoint(spec: InspectionSpec, req: ConnectionRequirement, idx: int,
                    obs: list[ObservationRecord], require_grounding: bool,
                    declared: frozenset[int] = frozenset(), insertion_confirmed: bool = False,
                    attestation: str | None = None) -> EndpointAssessment:
    """`declared`: photos the person inspecting declared show this endpoint's device (see device_declarations).
    `insertion_confirmed`: the person inspecting confirmed the Muse-only plug at this endpoint (assisted only)."""
    e = req.endpoints[idx]
    dev = spec.device(e.device_id)
    target = f"{dev.name} {e.port_label}" if e.flexible else f"{dev.name} port {e.port_label}"
    any_colour = ignores_colour(spec, req)
    want = base_color(req.cable_color)
    plug_word = f"{req.cable_color} plug" if req.cable_color else "plug"
    what = f"one of the permitted ports ({e.port_label})" if e.flexible else e.port_label
    concept = req.cable_concept()
    allow_inference = req.port_identity == "label_or_layout"
    # Several connector families on this device: an unknown family cannot justify negative evidence here.
    strict_family = dev.id in mixed_connector_devices(spec)
    support: list[EvidenceItem] = []
    weak: list[EvidenceItem] = []
    conflicts: list[EvidenceItem] = []
    unclear_matches: list[EvidenceItem] = []
    colour_uncertain: list[EvidenceItem] = []  # clear insertion, stated colour neither matches nor clearly differs
    inferred_only: list[EvidenceItem] = []
    hidden_label_plugs: list[EvidenceItem] = []  # matching plug in a port whose label could not be read
    permitted_empty: list[tuple[set[str], EvidenceItem]] = []  # flexible: a permitted port seen clearly empty
    other_cable: list[EvidenceItem] = []  # flexible: a permitted port holding a cable of another colour
    # flexible: a plug in a port whose legible label rules it out (e.g. 'WAN'). Guidance only; whether that is a
    # violation is decided by the existing criteria below (never by this list).
    not_permitted_plugs: list[str] = []
    empty_labels: list[str] = []  # flexible: printed text of the permitted ports seen clearly empty (for guidance)
    # flexible: printed label -> items. The same legible label on this device in two photos is the same port, so a
    # plug there in one photo and an empty port (or another cable) there in another is a contradiction, exactly as
    # for an exact endpoint. Ports identified only by socket shape carry no label and are never cross-matched.
    flex_claimed: dict[str, list[EvidenceItem]] = {}
    flex_negative: dict[str, list[EvidenceItem]] = {}
    # only_socket: the spec says the device has one socket of this family, so every observation of it (by label or
    # by shape) is the same port and is cross-matched under one key.
    only = e.selector is not None and e.selector.only_socket
    sam_empty: list[int] = []  # photos where SAM segmented no cable of this concept at all (guidance)
    illegible_ports = 0
    ports_seen = 0
    sides: set[str] = set()

    hits: list[tuple[ObservationRecord, SeenDevice]] = list(_device_hits(obs, e.device_id, "clear", declared))
    for o, d in hits:
        ext = o.extraction
        sides.add(d.visible_side)
        by_operator = d.identification_certainty != "clear"  # identity rests on a declaration in this photo
        for p in ext.ports:  # type: ignore[union-attr]
            if p.device_ref != d.ref:
                continue
            ports_seen += 1
            family = connector_match(p.connector_type, req.connector)
            if family == "mismatch":
                continue  # a socket of another connector family is never this requirement's port
            if p.label_legibility in ("partially_legible", "illegible"):
                illegible_ports += 1
            basis, how = identify_port(ext, d, p, e, dev, req.connector)
            item = EvidenceItem(seq=o.seq, image_id=o.image_id, port_ref=p.ref, device_ref=d.ref,
                                claim=f"{dev.name} {_port_desc(p)}" + (f" — {how}" if how else "")
                                      + (" — device identity declared by the person inspecting" if by_operator
                                         else ""),
                                grounding=o.port_links.get(f"{p.ref}|{concept}"), port_basis=basis,
                                device_basis="operator_declared" if by_operator else None)
            clear = p.insertion_visibility == "clear"
            inserted = p.occupancy == "cable_inserted"
            status, via = plug_colour_status(ext, p, want, req.connector, any_colour)
            colour_ok = clear and inserted and status == "match"
            if colour_ok and via == "cable":
                item = item.model_copy(update={"claim": item.claim + f" -> plug colourless; {want} cable "
                                                                     "visibly belongs to this port"})
            grounded = item.grounding is not None and item.grounding.corroborated
            # A colourless plug borrows the cable's colour only through the Muse link; that association must be
            # SAM-grounded even when grounding is otherwise not required (ablation runs).
            strong = grounded or (not require_grounding and via == "plug")
            if colour_ok and not strong and _sam_found_nothing(o, concept):
                sam_empty.append(o.seq)
            if basis in ("direct_label", "connector_shape") and e.flexible:
                # Flexible endpoint: one permitted port being empty or holding another cable does not rule the
                # requirement out - another permitted port may hold the cable.
                key = _ONLY if only else (normalize_label(_label_text(p) or "") if basis == "direct_label" else "")
                if colour_ok:
                    (support if strong else weak).append(item)
                    if key:
                        flex_claimed.setdefault(key, []).append(item)
                elif clear and p.occupancy == "empty":
                    permitted_empty.append((_legible_labels(p), item.model_copy(update={
                        "claim": item.claim + " -> permitted port is empty"})))
                    empty_labels.append(_label_text(p) or f"an unlabelled {req.connector} socket")
                    if key:
                        flex_negative.setdefault(key, []).append(permitted_empty[-1][1])
                elif clear and inserted and status == "mismatch":
                    other_cable.append(item.model_copy(update={
                        "claim": item.claim + f" -> holds a {base_color(p.plug_color)} plug, not {want}"}))
                    if key:
                        flex_negative.setdefault(key, []).append(other_cable[-1])
                elif clear and inserted and p.plug_color and status == "uncertain":
                    colour_uncertain.append(item.model_copy(update={
                        "claim": item.claim + f" -> stated plug colour '{p.plug_color}' is not clearly {want} nor "
                                              "clearly another colour"}))
                else:
                    unclear_matches.append(item)
            elif basis == "direct_label":
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
                if (e.flexible and p.occupancy == "cable_inserted" and p.insertion_visibility == "clear"
                        and other_port(p, e)):
                    not_permitted_plugs.append(f"photo {o.seq}: '{_label_text(p)}'")
                if (req.cable_identity == "unique_in_installation" and p.label_legibility == "legible"
                        and other_port(p, e) and clear and inserted and status == "match" and via == "plug"
                        and (family == "match" or not strict_family)):
                    conflicts.append(item.model_copy(update={
                        "claim": item.claim + f" -> the (spec-unique) {want} cable is in the wrong port"}))

    sel = e.selector
    if sel is not None and sel.allowed_labels and not sel.allowed_group and not sel.any_socket_of_connector:
        # A finite list of permitted ports: the requirement is ruled out only if EVERY listed port is seen clearly
        # empty (static installation, current configuration).
        listed = e.accepted_labels()
        if listed and listed <= set().union(*(labels for labels, _ in permitted_empty)):
            conflicts.extend(item.model_copy(update={"claim": item.claim + "; every permitted port is clearly empty"})
                             for _, item in permitted_empty)

    for key, claimed in flex_claimed.items():
        for x in flex_negative.get(key, []):
            if any(c.seq != x.seq for c in claimed):
                same = (f"the {dev.name}'s only {req.connector} socket (per the spec)" if key == _ONLY
                        else "this same labelled port")
                conflicts.append(x.model_copy(update={
                    "claim": x.claim + f"; {_seqs([c.seq for c in claimed])} reported a plug in {same}"}))

    def gap(code, fact, **ctx) -> Gap:
        return Gap(requirement_id=req.id, code=code, endpoint_index=idx, target=target,
                   missing_fact=fact, context={"device_id": dev.id, "device": dev.name,
                                               "device_description": dev.description,
                                               "port_label": e.port_label, **ctx})

    def result(state, g=None, **kw) -> EndpointAssessment:
        return EndpointAssessment(index=idx, device_id=e.device_id, port_label=e.port_label, state=state,
                                  inferred_only=inferred_only, candidates=weak, gap=g, **kw)

    if insertion_confirmed and not support and not conflicts and (ok := confirmable(obs, req, weak)):
        # Assisted only: a statement can complete a plug Muse saw clearly at an identified port; never against any
        # contrary observation (then the endpoint is contradicted below and the statement is not used).
        support = [x.model_copy(update={
            "insertion_basis": "operator_confirmed",
            "claim": x.claim + " — SAM did not corroborate; insertion confirmed by the person inspecting"}) for x in ok]
        weak = [x for x in weak if x not in ok]
    if attestation and not support and not conflicts:
        # Assisted only: a written attestation stands in for photo evidence of this end; never against any contrary
        # observation (an empty socket or another plug keeps the endpoint contradicted/violated/unknown).
        support = [EvidenceItem(seq=0, image_id="operator_attestation", attested=True,
                                claim=f"Attested by the person inspecting; no photo established this: \"{attestation}\"")]
    claimed_support = support + weak
    # A declaration supports identity only: negative evidence from a photo whose device identity rests on it never
    # establishes a violation on its own (it still blocks verification as a contradiction, below).
    hard_conflicts = [x for x in conflicts if x.device_basis is None]
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
    if hard_conflicts:
        return result("violated", conflicts=conflicts)
    if weak:
        fact = (f"Muse reports a {plug_word} in {target} ({_photos(weak)}), but SAM did not segment a "
                f"'{concept}' reaching that port, so it is recorded as observed but not corroborated.")
        if sam_empty:
            fact += (f" In {_seqs(sam_empty)} SAM segmented no '{concept}' anywhere in the photo: another camera "
                     "angle may not change this.")
        else:
            fact += " A closer, unobstructed view of the plug and the cable leaving it is needed."
        may_confirm = (spec.assisted is not None and spec.assisted.confirmable_insertions
                       and bool(confirmable(obs, req, weak)))
        if may_confirm:
            fact += (" This template lets you confirm the plug yourself; the connection would then be marked as "
                     "relying on your statement.")
        g = gap("GROUNDING_MISSING", fact, sam_segmented_nothing_in=sorted(set(sam_empty)),
                muse_only_photos=sorted({x.seq for x in weak}), declaration_permitted=may_confirm)
    elif colour_uncertain:
        g = gap("INSERTION_UNCLEAR",
                f"{target} holds a plug whose colour could not be established as {req.cable_color} (nor clearly as "
                "another colour); a closer view in good light of the plug and the cable leaving it is needed.",
                colour_ambiguous=True,
                observed=[f"[{x.image_id}] {x.claim}" for x in colour_uncertain][:3])
    elif unclear_matches:
        g = gap("INSERTION_UNCLEAR",
                f"{target} was found, but whether a {plug_word} is clearly inserted is not visible.")
    elif (not hits or ports_seen == 0) and (unconfirmed := _unconfirmed_port_photos(obs, e.device_id, declared)):
        seqs = sorted(unconfirmed)
        g = gap("DEVICE_UNCONFIRMED",
                f"Ports were photographed ({_seqs(seqs)}) on a device that may be the {dev.name}, but it was not "
                f"identified with certainty in that photo, so those ports are not used as evidence. One photo needs "
                f"to show the {dev.name}'s identifying features together with its connection ports.",
                unconfirmed_port_photos=seqs,
                identification_basis=[f"photo {k}: {v}" for k, v in sorted(unconfirmed.items())][:3],
                declaration_permitted=spec.allow_device_identity_declarations)
    elif not hits:
        uncertain = any(True for _ in _device_hits(obs, e.device_id, "uncertain", declared))
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
        fact = (f"A {plug_word} was seen in a {dev.name} port whose own printed label is not "
                f"readable (likely hidden by the plug), so it is not established that this is {what}.")
        if layout_ok:
            fact += (" Neighbouring labels place it at the declared position of "
                     f"{e.port_label}, but this requirement accepts only a directly readable label.")
        if e.flexible and empty_labels:
            fact += (f" Permitted ports seen empty: {', '.join(dict.fromkeys(empty_labels))}. That does not show "
                     "where the cable is; the identity of the occupied port is what is unresolved.")
        g = gap("LABEL_ILLEGIBLE", fact, sides_seen=sorted(sides), label_hidden_by_plug=True,
                layout_inference_available=layout_ok,
                candidate_ports=[f"[{x.image_id}] {x.claim}" for x in inferred_only + hidden_label_plugs][:4],
                **({"permitted_ports_seen_empty": list(dict.fromkeys(empty_labels))}
                   if e.flexible and empty_labels else {}))
    elif illegible_ports:
        g = gap("LABEL_ILLEGIBLE",
                f"Ports on the {dev.name} were seen, but labels were not legible enough to find {what}.",
                sides_seen=sorted(sides))
    elif e.flexible:
        seen_empty = [x for _, x in permitted_empty]
        fact = f"No observed port on the {dev.name} was identified as {e.port_label} holding the {req.cable_desc()}."
        if seen_empty or other_cable:
            fact += (f" Permitted ports seen so far: {len(seen_empty)} empty, {len(other_cable)} holding another "
                     "cable; another permitted port may hold it.")
        if not_permitted_plugs:
            fact += (" A plug was seen in a port whose printed label is not a permitted one ("
                     + ", ".join(dict.fromkeys(not_permitted_plugs)) + "); that port does not satisfy this "
                     "requirement.")
        if only and seen_empty:
            fact += (f" The spec says the {dev.name} has only one {req.connector} socket; it was seen empty in "
                     f"{_photos(seen_empty)}.")
        g = gap("PORT_NOT_FOUND", fact, sides_seen=sorted(sides),
                permitted_ports_seen=[f"[{x.image_id}] {x.claim}" for x in seen_empty + other_cable][:4],
                **({"plugs_in_ports_not_permitted": list(dict.fromkeys(not_permitted_plugs))[:4]}
                   if not_permitted_plugs else {}))
    else:
        g = gap("PORT_NOT_FOUND", f"No observed port on the {dev.name} was legibly labelled {e.port_label}.",
                sides_seen=sorted(sides))
    # Conflicts that rest only on a declared device identity are kept on the record, never as a verdict.
    return result("unknown", g, conflicts=conflicts)


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
    any_colour = ignores_colour(spec, req)
    concept = req.cable_concept()
    allow_inference = req.port_identity == "label_or_layout"
    strict = mixed_connector_devices(spec)
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
            if (c.path_visibility != "fully_traced" or (not any_colour and compare_color(c.color, want) != "match")
                    or connector_match(c.connector_type, req.connector) == "mismatch"):
                continue
            ends, why, attached, elsewhere = [], [], [], []
            for e in req.endpoints:
                hit, reason, seen, other = None, "", False, None
                for pr in c.connected_port_refs:
                    p, d = ports[pr], devs.get(ports[pr].device_ref)
                    if d is None or d.spec_device_id != e.device_id or p.occupancy != "cable_inserted":
                        continue
                    family = connector_match(p.connector_type, req.connector)
                    if family == "mismatch":
                        continue  # socket of another connector family: not where this cable ends
                    seen = True
                    if plug_colour_status(ext, p, want, req.connector, any_colour)[0] != "match":  # type: ignore[arg-type]
                        reason = f"{pr} holds a {p.plug_color} plug"
                        continue
                    link = o.port_links.get(f"{pr}|{concept}")
                    if require_grounding and not (link and link.corroborated):
                        reason = f"{pr} is not SAM-grounded"
                        continue
                    basis, _ = identify_port(ext, d, p, e, spec.device(e.device_id), req.connector)  # type: ignore[arg-type]
                    if basis in ("direct_label", "connector_shape") or (basis == "layout_inference" and allow_inference):
                        hit = (p, basis)
                        break
                    if other_port(p, e) and (family == "match" or e.device_id not in strict):
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
                    port_basis=next((b for _, b in ends if b != "direct_label"), "direct_label"),
                    claim=f"{c.color} cable {c.ref} traced continuously between " + " and ".join(desc)
                          + (", SAM-grounded at both ports" if require_grounding else "")))
            elif all(attached):
                near.append(f"[photo {o.seq} · {o.image_id}] {c.color} cable {c.ref} is fully traced between the "
                            "two devices, but " + "; ".join(w for w, h in zip(why, ends) if not h))
    return out, near, conflicts


def _seqs(seqs: list[int]) -> str:
    return ", ".join(f"photo {s}" for s in sorted(set(seqs))) or "no photo"


def _photos(items: list[EvidenceItem]) -> str:
    seqs = sorted({x.seq for x in items})
    return ", ".join([f"photo {s}" for s in seqs if s > 0] + (["your written attestation"] if 0 in seqs else [])) \
        or "none"


def _observed_family(obs: list[ObservationRecord], x: EvidenceItem) -> str | None:
    """The connector family Muse explicitly reported for the port of evidence item x (None if not reported)."""
    o = next((o for o in obs if o.seq == x.seq), None)
    if o is None or o.extraction is None:
        return None
    p = next((p for p in o.extraction.ports if p.ref == x.port_ref), None)
    return p.connector_type if p is not None and p.connector_type not in (None, "unclear") else None


def assess_requirement(spec: InspectionSpec, req: ConnectionRequirement, obs: list[ObservationRecord],
                       require_grounding: bool = True,
                       declarations: list[OperatorDeclaration] | tuple = ()) -> RequirementAssessment:
    """`declarations`: operator declarations of the CURRENT configuration (the caller filters by epoch). Used only
    where the spec permits them; see device_declarations and the cable-identity rules below."""
    declared_devices = device_declarations(spec, declarations)
    seated = insertion_confirmations(spec, declarations)
    attested = attestations(spec, declarations)
    eps = [assess_endpoint(spec, req, i, obs, require_grounding,
                           declared_devices.get(req.endpoints[i].device_id, frozenset()), (req.id, i) in seated,
                           attested.get((req.id, i)))
           for i in range(2)]
    may_attest = spec.assisted is not None and spec.assisted.allow_attestations
    for ep in eps:
        if may_attest and ep.gap is not None and ep.state == "unknown" and not ep.conflicts:
            ep.gap.context["attestation_permitted"] = True
    gaps = [ep.gap for ep in eps if ep.gap]
    contradictions = [f"{ep.device_id} {ep.port_label}: "
                      + "; ".join(f"[{x.image_id}] {x.claim}" for x in ep.support + ep.conflicts)
                      for ep in eps if ep.state == "contradicted"]
    assumptions: list[str] = []
    operator: list[str] = []
    identity_state = "not_evaluated"
    identity_ev: list[EvidenceItem] = []

    ambiguity = _ambiguity_note(spec, req, obs)
    run_word = f"{req.cable_color} cable" if req.cable_color else req.cable_type

    violated = [ep for ep in eps if ep.state == "violated"]
    if violated:
        why = "; ".join(f"[photo {c.seq}] {c.claim}" for ep in violated for c in ep.conflicts)
        by_spec = any("(spec-unique)" in c.claim for ep in violated for c in ep.conflicts)
        return RequirementAssessment(requirement_id=req.id, status="VIOLATED",
                                     explanation=f"Clearly observed: {why}." + ambiguity, endpoints=eps,
                                     identity_state=identity_state, gaps=gaps,
                                     contradictions=contradictions,
                                     assurance="spec_assumption" if by_spec else "visual")

    for ep in eps:
        shaped = [s for s in ep.support if s.port_basis == "connector_shape"]
        if shaped:
            assumptions.append(f"{spec.device(ep.device_id).name} {ep.port_label} was identified in "
                               f"{_photos(shaped)} by its observed {req.connector} socket shape, not a printed label: "
                               f"the spec accepts any {req.connector} socket on that device.")
        inferred = [s for s in ep.support if s.port_basis == "layout_inference"]
        if inferred:
            assumptions.append(f"{spec.device(ep.device_id).name} {ep.port_label} was identified by layout "
                               f"inference in {_photos(inferred)} (its own label was not readable); this relies "
                               "on the spec-declared port order.")
        fallback = [s for s in ep.support if s.grounding is not None and s.grounding.concept != req.cable_concept()]
        if ep.support and len(fallback) == len(ep.support):
            assumptions.append(f"{spec.device(ep.device_id).name} {ep.port_label}: in {_photos(fallback)} SAM's "
                               f"'{req.cable_concept()}' concept segmented nothing, and a generic "
                               f"'{fallback[0].grounding.concept}' mask reaching the port corroborated that a "  # type: ignore[union-attr]
                               "cable is there. That it is "
                               f"{req.connector.upper() if req.connector == 'hdmi' else req.connector} is Muse's "
                               "reading of the connector, not SAM's.")
        declared = [s for s in ep.support if s.device_basis == "operator_declared"]
        if ep.support and len(declared) == len(ep.support):
            operator.append(f"You confirmed that the device in {_photos(declared)} is the "
                            f"{spec.device(ep.device_id).name}; Muse could not identify it with certainty there.")
        if any(s.attested for s in ep.support):
            note = next(s.claim for s in ep.support if s.attested).split(": ", 1)[-1]
            operator.append(f"You attested the {spec.device(ep.device_id).name} {ep.port_label} end in writing; no "
                            f"photo established it: {note}")
        seated_items = [s for s in ep.support if s.insertion_basis == "operator_confirmed"]
        if seated_items:
            operator.append(f"You confirmed that the {req.connector} plug Muse saw in {_photos(seated_items)} is "
                            f"seated in the {spec.device(ep.device_id).name} {ep.port_label}; SAM did not "
                            "corroborate it.")
    both = all(ep.state == "established" for ep in eps)
    traced, near, trace_conflicts = identity_evidence(spec, req, obs, require_grounding)
    unique = req.cable_identity == "unique_in_installation"
    may_declare = req.cable_identity == "trace_or_operator_declaration"
    cable_declared = may_declare and any(x.kind == "cable_identity" and x.requirement_id == req.id
                                         for x in declarations)
    # The cable-identity declaration is accepted only for two endpoints that photos already support, where Muse
    # explicitly reported the requirement's connector family at both ports, and where no photo traces either
    # endpoint's cable somewhere else. It never replaces a trace and never resolves a contradiction.
    families_ok = both and all(any(s.attested or _observed_family(obs, s) == req.connector for s in ep.support)
                               for ep in eps)
    declaration_contradicted = cable_declared and bool(trace_conflicts) and not traced
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
        if (identity_state == "unknown" and cable_declared and both and families_ok and not trace_conflicts
                and not contested):
            identity_state = "declared_by_operator"
            ends = " and ".join(f"{spec.device(x.device_id).name} {x.port_label}" for x in req.endpoints)
            operator.append(f"You declared that the {run_word} at {ends} is one cable. No photo traced it end to "
                            "end; this link rests on your declaration.")
    if declaration_contradicted:
        contradictions.append("cable identity: the operator declared one cable between both endpoints, but "
                              + "; ".join(f"[{x.image_id}] {x.claim}" for x in trace_conflicts))
        gaps.append(Gap(requirement_id=req.id, code="CONTRADICTION", endpoint_index=None,
                        target=f"the {run_word} run between both endpoints",
                        missing_fact=(f"Your declaration that one {run_word} joins both endpoints is contradicted by "
                                      f"{_photos(trace_conflicts)}, which trace an endpoint's cable to a different "
                                      "port. The declaration is not used; the installation needs review."),
                        context={"images": sorted({x.image_id for x in trace_conflicts}),
                                 "trace_conflicts": [f"[{x.image_id}] {x.claim}" for x in trace_conflicts][:3]}))
    elif contested:
        opposing = (traced if not unique else []) + trace_conflicts
        contradictions.append("cable identity: " + "; ".join(f"[{x.image_id}] {x.claim}" for x in opposing))
        gaps.append(Gap(requirement_id=req.id, code="CONTRADICTION", endpoint_index=None,
                        target=f"the {run_word} run between both endpoints",
                        missing_fact=("Photos disagree about where the "
                                      f"{run_word} runs: {_photos(opposing)} trace it to different "
                                      "ports. An unchanged installation has one cable per plug, so this conflict "
                                      "cannot be resolved by choosing one photo. If the equipment was physically "
                                      "changed between photos, the change must be declared so earlier photos stop "
                                      "counting."),
                        context={"images": sorted({x.image_id for x in opposing}),
                                 "trace_conflicts": [f"[{x.image_id}] {x.claim}" for x in trace_conflicts][:3]}))
    elif not unique:
        if both and not identity_ev and identity_state != "declared_by_operator":
            blocked = None
            if may_declare and not families_ok:
                blocked = ("a declaration cannot be used yet: Muse did not explicitly report the "
                           f"{req.connector} connector at both supported ports")
            elif may_declare and trace_conflicts:
                blocked = "a declaration cannot be used: a photo traces an endpoint's cable to a different port"
            gaps.append(Gap(requirement_id=req.id, code="CABLE_CONTINUITY", endpoint_index=None,
                            target=f"the {run_word} run between both endpoints",
                            missing_fact=("Both ends show a matching plug, but no single photo shows the "
                                          "same cable running continuously between the two identified ports."
                                          + (" Near miss: " + " | ".join(near[:2]) if near else "")
                                          + (" The spec allows you to declare that it is one cable instead; "
                                             "the verdict would then be marked as relying on your declaration."
                                             if may_declare and not blocked else "")
                                          + (f" ({blocked}.)" if blocked else "")),
                            context={"endpoints": [f"{spec.device(x.device_id).name} {x.port_label}"
                                                   for x in req.endpoints], "near_misses": near[:3],
                                     "declaration_permitted": may_declare and not blocked}))
    if both and identity_state in ("established", "assumed_by_spec", "declared_by_operator"):
        where = "; ".join(f"{spec.device(ep.device_id).name} {ep.port_label} from {_photos(ep.support)}"
                          for ep in eps)
        how = {"established": f"; cable identity traced in {_photos(identity_ev)}.",
               "assumed_by_spec": "; cable identity relies on a spec assertion.",
               "declared_by_operator": "; cable identity rests on the operator's declaration (not traced in any "
                                       "photo)."}[identity_state]
        return RequirementAssessment(
            requirement_id=req.id, status="VERIFIED",
            explanation="Both endpoints observed with identified ports, clear insertion and "
                        + ("matching colour" if req.cable_color else "a plug inserted (any cable colour accepted)")
                        + (", SAM-grounded" if require_grounding else "") + f" ({where})" + how + ambiguity,
            endpoints=eps, identity_state=identity_state, identity_evidence=identity_ev,
            assumptions=assumptions, operator_declarations=operator,
            assurance=("operator_attested" if any(s.attested for ep in eps for s in ep.support)
                       else "operator_assisted" if operator else "spec_assumption" if assumptions else "visual"))

    missing = "; ".join(g.missing_fact for g in gaps)
    if trace_conflicts and not contested and not any(g.code == "CABLE_CONTINUITY" for g in gaps):
        missing += ". Conflicting trace (not counted as evidence): " + "; ".join(
            f"[photo {x.seq}] {x.claim}" for x in trace_conflicts[:2])
    if ambiguity and "more than one device was identified" not in missing:
        missing += "." + ambiguity
    return RequirementAssessment(requirement_id=req.id, status="INSUFFICIENT_EVIDENCE",
                                 explanation=f"Not established: {missing}", endpoints=eps,
                                 identity_state=identity_state, identity_evidence=identity_ev,
                                 gaps=gaps, contradictions=contradictions, assumptions=assumptions,
                                 operator_declarations=operator)


def overall_assessment(assessments: list[RequirementAssessment]) -> OverallAssessment | None:
    """The installation verdict over all requirements, derived only from the per-requirement verdicts:
    VIOLATED if any requirement is VIOLATED; VERIFIED only if every requirement is VERIFIED; otherwise
    INSUFFICIENT_EVIDENCE. Requirements with unresolved contradictions are listed, never folded away."""
    if not assessments:
        return None
    by = {s: [a.requirement_id for a in assessments if a.status == s]
          for s in ("VERIFIED", "VIOLATED", "INSUFFICIENT_EVIDENCE")}
    review = [a.requirement_id for a in assessments if a.contradictions]
    if by["VIOLATED"]:
        status, why = "VIOLATED", f"{', '.join(by['VIOLATED'])} clearly violated"
    elif len(by["VERIFIED"]) == len(assessments):
        status, why = "VERIFIED", f"all {len(assessments)} requirement(s) verified"
    else:
        status, why = "INSUFFICIENT_EVIDENCE", f"{', '.join(by['INSUFFICIENT_EVIDENCE'])} not established"
    explanation = f"{why} ({'; '.join(f'{a.requirement_id} {a.status}' for a in assessments)})."
    if review:
        explanation += f" Contradictory evidence needs review for {', '.join(review)}."
    assurance = None
    if status == "VERIFIED":
        order = ["visual", "spec_assumption", "operator_assisted", "operator_attested"]
        assurance = max((a.assurance or "visual" for a in assessments), key=order.index)
    return OverallAssessment(status=status, explanation=explanation,
                             requirement_statuses={a.requirement_id: a.status for a in assessments},
                             review_required=review, assurance=assurance)


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


_GAP_PRIORITY = ["CONTRADICTION", "DEVICE_NOT_SEEN", "DEVICE_UNCONFIRMED", "PORTS_NOT_VISIBLE", "LABEL_ILLEGIBLE",
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
