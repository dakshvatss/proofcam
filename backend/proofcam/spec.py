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


class EndpointSpec(_Strict):
    device_id: str
    port_label: str
    label_aliases: list[str] = Field(default_factory=list)

    def accepted_labels(self) -> set[str]:
        return {normalize_label(x) for x in [self.port_label, *self.label_aliases]}


class ConnectionRequirement(_Strict):
    id: str
    kind: Literal["connection"] = "connection"
    text: str
    cable_color: str
    cable_type: str = "ethernet cable"
    endpoints: tuple[EndpointSpec, EndpointSpec]
    # How cable identity across endpoints may be established:
    #   require_trace          - one image must show the same cable continuously between both ports.
    #   unique_in_installation - the spec author asserts exactly one cable of this colour/type exists,
    #                            so endpoint observations may be joined. Disclosed in every report.
    cable_identity: Literal["require_trace", "unique_in_installation"] = "require_trace"
    sam_concept: str | None = None

    def cable_concept(self) -> str:
        return self.sam_concept or f"{self.cable_color} {self.cable_type}"


Requirement = ConnectionRequirement


class InspectionSpec(_Strict):
    id: str
    title: str
    devices: list[DeviceSpec]
    requirements: list[Requirement]

    @model_validator(mode="after")
    def _check_refs(self) -> InspectionSpec:
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
