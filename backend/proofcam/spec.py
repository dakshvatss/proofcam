"""Inspection specifications: authored by people, never by the model."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeviceSpec(_Strict):
    id: str
    name: str
    description: str = Field(description="Visual description used to recognise the device.")
    sam_concept: str = Field(description="Short noun phrase for SAM concept segmentation, e.g. 'router'.")
    # Optional author-declared physical layout: each row lists port labels left-to-right as seen when
    # facing the ports. Used ONLY for neighbour-label inference (policy.infer_port_identity), and only
    # where a requirement opts in with port_identity="label_or_layout".
    port_rows: list[list[str]] = Field(default_factory=list)


# Hard upper bound for a spec's own photo budget (InspectionSpec.max_photos). The per-inspection model-call budget and
# the server-wide call cap still bind independently (a photo costs model calls; more photos never raise either cap).
MAX_PHOTOS_LIMIT = 16


class PortSelector(_Strict):
    """Flexible endpoint (M3.5): ANY port matching one of these rules satisfies the endpoint.

    allowed_labels           - any of these exact printed labels (e.g. ["LAN 1", "LAN 2"]).
    allowed_group            - any port whose legible printed label (or group heading) is this word, optionally
                               followed by a number: "LAN" accepts "LAN 3" or "3" under a "LAN" heading, never
                               "WAN"; "HDMI" accepts "HDMI 2", never "HDMI OUT".
    excluded_labels          - printed labels that never qualify, whatever else matches.
    any_socket_of_connector  - the spec author asserts that EVERY socket of the requirement's connector family on
                               this device is acceptable (e.g. every HDMI input on a TV; a console's only Ethernet
                               socket). The port is then identified by its OBSERVED socket shape only - never from
                               the expectation - and the assumption is disclosed in every report.

    only_socket              - the spec author asserts the device has exactly ONE socket of the requirement's connector
                               family (e.g. a console's single LAN port). Observations of it in different photos, by
                               label or by shape, are then the same port: a plug there in one photo and that socket
                               clearly empty (or holding another cable) in another is a CONTRADICTION. It only ever
                               blocks verification; it never creates a violation on its own.

    A port that none of the rules identifies does not qualify (unknown is never acceptable). Flexible endpoints never
    turn one empty permitted port into a violation, because another permitted port may hold the cable.
    """

    allowed_labels: list[str] = Field(default_factory=list)
    allowed_group: str | None = None
    excluded_labels: list[str] = Field(default_factory=list)
    any_socket_of_connector: bool = False
    only_socket: bool = False

    @model_validator(mode="after")
    def _some_rule(self) -> PortSelector:
        if not (self.allowed_labels or self.allowed_group or self.any_socket_of_connector):
            raise ValueError("a port selector needs allowed_labels, allowed_group or any_socket_of_connector")
        return self


class EndpointSpec(_Strict):
    device_id: str
    # Exact endpoint: the printed label of the one required port. With a selector it is only the display name of
    # the endpoint (e.g. "any LAN port") and is never matched against photos.
    port_label: str
    label_aliases: list[str] = Field(default_factory=list)
    selector: PortSelector | None = None

    @model_validator(mode="after")
    def _selector_or_aliases(self) -> EndpointSpec:
        if self.selector is not None and self.label_aliases:
            raise ValueError("label_aliases apply to exact endpoints only; use selector.allowed_labels")
        return self

    @property
    def flexible(self) -> bool:
        return self.selector is not None

    def accepted_labels(self) -> set[str]:
        """Normalized printed labels that identify this endpoint directly (exact: label + aliases)."""
        if self.selector is not None:
            return {normalize_label(x) for x in self.selector.allowed_labels}
        return {normalize_label(x) for x in [self.port_label, *self.label_aliases]}


# Physical connector families a requirement can name. Observations use the same words (plus "other"/"unclear"),
# so a port or cable of one family can never stand in for a requirement of another.
ConnectorType = Literal["ethernet", "hdmi", "usb", "power", "optical", "coaxial"]


class ConnectionRequirement(_Strict):
    id: str
    kind: Literal["connection"] = "connection"
    text: str
    # One base colour the cable must have, or null = any colour (identity and continuity are still required).
    cable_color: str | None
    cable_type: str = "ethernet cable"
    # Connector family of this cable at both ends (ethernet = RJ45). Default keeps older specs unchanged.
    connector: ConnectorType = "ethernet"
    endpoints: tuple[EndpointSpec, EndpointSpec]
    # How cable identity across endpoints may be established:
    #   require_trace          - one image must show the same cable continuously between both ports.
    #   unique_in_installation - the spec author asserts exactly one cable of this colour/type exists,
    #                            so endpoint observations may be joined. Disclosed in every report.
    #   trace_or_operator_declaration
    #                          - a single-photo trace as for require_trace (the strongest standard); failing that,
    #                            the person inspecting may declare that the two independently supported endpoints hold
    #                            one cable. Never accepted against a contradicting trace or an open contradiction; the
    #                            verdict is then marked operator-assisted and the declaration disclosed in every report.
    cable_identity: Literal["require_trace", "unique_in_installation", "trace_or_operator_declaration"] = "require_trace"
    sam_concept: str | None = None
    # How a port may be identified:
    #   label_only      - its own printed label must be legible in the image (default).
    #   label_or_layout - additionally, a port whose label is hidden may be identified from legible
    #                     neighbouring labels + the device's declared port_rows. Disclosed as an
    #                     assumption in every report; never used to establish a violation.
    port_identity: Literal["label_only", "label_or_layout"] = "label_only"

    @model_validator(mode="after")
    def _identity_needs_a_colour(self) -> ConnectionRequirement:
        # "The only Ethernet cable" is too weak to join endpoint observations: other cables of the same type (a
        # router's WAN cable) are common. A spec-asserted unique cable must also be unique by colour.
        if self.cable_identity == "unique_in_installation" and not self.cable_color:
            raise ValueError("cable_identity 'unique_in_installation' needs a cable_color")
        if self.port_identity == "label_or_layout" and any(e.flexible for e in self.endpoints):
            raise ValueError("layout inference applies to exact endpoints only")
        return self

    def cable_desc(self) -> str:
        """'blue ethernet cable', or 'ethernet cable' when any colour is accepted."""
        return f"{self.cable_color} {self.cable_type}" if self.cable_color else self.cable_type

    def cable_concept(self) -> str:
        return self.sam_concept or self.cable_desc()


Requirement = ConnectionRequirement


class AssistedMode(_Strict):
    """Usability rules for an OPERATOR-ASSISTED template (M3.8). Only a spec that sets `assisted` gets them; every other
    template keeps the default rules. None of them can produce a verdict from Muse alone: anything that would rely on
    an unverified fact needs an explicit operator statement and is marked operator-assisted.

    ignore_cable_color      - cable colour is recorded but never accepts or rejects a plug (connector family still
                              must match: an HDMI plug in an RJ45 socket is never this requirement's plug).
    confirmable_insertions  - a plug Muse saw clearly, at a port identified by label or socket shape, with the
                              requirement's connector family explicitly reported, but which SAM did not corroborate,
                              may be confirmed by the person inspecting. Refused where any photo contradicts it.
    max_attempts_per_gap    - targeted camera requests per open fact; then guidance moves on (no re-framing loops).
    suppress_micro_adjustments - planner instructions that are only small re-framings ("2 inches left", "tilt
                              slightly") are replaced by the fixed template for the missing fact.
    """

    ignore_cable_color: bool = True
    confirmable_insertions: bool = True
    max_attempts_per_gap: int = Field(1, ge=1, le=3)
    suppress_micro_adjustments: bool = True
    # The person inspecting may attest an endpoint the photos could not establish, with a typed note of what they
    # checked. Never against contrary photo evidence; verdicts relying on it are labelled operator-attested.
    allow_attestations: bool = False


class InspectionSpec(_Strict):
    id: str
    title: str
    devices: list[DeviceSpec]
    requirements: list[Requirement]
    # Photos this inspection may use; null = the server default (6). Bounded by MAX_PHOTOS_LIMIT.
    max_photos: int | None = Field(None, ge=1, le=MAX_PHOTOS_LIMIT)
    # The person inspecting may confirm that a device Muse claimed only UNCERTAINLY in one photo (e.g. a close-up of a
    # TV's side panel without its logo) is the spec device. Disclosed as an operator assumption; never applied to a
    # photo where Muse matched another spec device or where two devices claim the same one.
    allow_device_identity_declarations: bool = False
    # Operator-assisted usability rules (see AssistedMode); None = the default rules.
    assisted: AssistedMode | None = None

    @model_validator(mode="after")
    def _check_refs(self) -> InspectionSpec:
        # Draft templates mark facts still to be confirmed on the real hardware with "TODO". Such a spec is not a
        # description of a real installation and must never be loaded as ready to run.
        if "TODO" in self.model_dump_json():
            raise ValueError("specification still contains TODO placeholders (unconfirmed hardware facts)")
        ids = {d.id for d in self.devices}
        if len(ids) != len(self.devices):
            raise ValueError("duplicate device id")
        req_ids = [r.id for r in self.requirements]
        if len(set(req_ids)) != len(req_ids):
            raise ValueError("duplicate requirement id")
        for r in self.requirements:
            for e in r.endpoints:
                if e.device_id not in ids:
                    raise ValueError(f"requirement {r.id} references unknown device {e.device_id}")
        # A colour would still shape the SAM concept ("blue ethernet cable") and the wording; an assisted spec that
        # ignores colour must not name one at all.
        if self.assisted is not None and self.assisted.ignore_cable_color \
                and any(r.cable_color for r in self.requirements):
            raise ValueError("assisted.ignore_cable_color needs cable_color null on every requirement")
        return self

    def device(self, device_id: str) -> DeviceSpec:
        return next(d for d in self.devices if d.id == device_id)

    def requirement(self, req_id: str) -> Requirement:
        return next(r for r in self.requirements if r.id == req_id)

    @classmethod
    def load(cls, path: str | Path) -> InspectionSpec:
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


_LABEL_PREFIXES = ("PORT", "PRT", "P")


def normalize_label(label: str) -> str:
    """Canonical form for port-label comparison: 'LAN 1' == 'lan-1' == 'LAN1'.

    A bare 'Port 3' / 'P3' normalizes to '3'. Different words never collapse
    (e.g. 'LAN1' != '1'); use label_aliases in the spec for that.
    """
    s = re.sub(r"[\s\-_./#:]+", "", label.upper())
    for p in _LABEL_PREFIXES:
        if s.startswith(p) and s[len(p):].isdigit():
            return s[len(p):]
    return s
