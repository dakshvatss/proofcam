"""Schemas for model-derived data.

Everything in this module is a *claim made by a model*. Nothing here is a verdict.
The deterministic policy (policy.py) decides what these claims allow us to conclude.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Box1000(_Strict):
    """Muse Spark perception-grounding box on the documented 0-1000 grid of the sent image."""

    x1: int
    y1: int
    x2: int
    y2: int

    @model_validator(mode="after")
    def _valid(self) -> Box1000:
        for v in (self.x1, self.y1, self.x2, self.y2):
            if not 0 <= v <= 1000:
                raise ValueError("box coordinate outside 0-1000 grid")
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("degenerate box")
        return self

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Half-open pixel box on the image that was sent to the model."""
        return (
            round(self.x1 * width / 1000),
            round(self.y1 * height / 1000),
            round(self.x2 * width / 1000),
            round(self.y2 * height / 1000),
        )


Certainty = Literal["clear", "uncertain"]

# Physical connector family as SEEN (shape of the socket/plug). Same words as spec.ConnectorType, plus "other" (a
# connector of none of these families) and "unclear" (cannot be told from the photo). Defaults to "unclear" so
# observations recorded before this field existed keep their meaning.
ObservedConnector = Literal["ethernet", "hdmi", "usb", "power", "optical", "coaxial", "other", "unclear"]


class SeenDevice(_Strict):
    ref: str = Field(description="Image-local id, e.g. 'D1'.")
    spec_device_id: str | None = Field(description="Matching device id from the spec, or null if none/unsure.")
    identification_basis: str = Field(description="Visible cues used to identify it (label text, shape, LEDs).")
    identification_certainty: Certainty
    visible_side: Literal["front", "rear", "top", "left_side", "right_side", "unknown"]
    ports_visible: bool
    box: Box1000 | None


class PortObservation(_Strict):
    ref: str = Field(description="Image-local id, e.g. 'P1'.")
    device_ref: str
    label_read: str | None = Field(description="Exact label text read for this port; null if unreadable.")
    label_group: str | None = Field(description="Group heading printed above/beside a set of ports, e.g. 'LAN'.")
    label_legibility: Literal["legible", "partially_legible", "illegible", "no_label"]
    occupancy: Literal["cable_inserted", "empty", "unclear"]
    plug_color: str | None = Field(description="Colour of the plug/cable in the port; null if empty or unclear.")
    insertion_visibility: Literal["clear", "partial", "occluded"]
    box: Box1000 | None
    connector_type: ObservedConnector = Field(
        "unclear", description="Connector family of this socket judged from its visible shape (ethernet = RJ45); "
                               "'unclear' if the shape cannot be seen.")


class CableObservation(_Strict):
    ref: str = Field(description="Image-local id, e.g. 'C1'.")
    color: str
    connector_type: ObservedConnector = Field(
        "unclear", description="Connector family of this cable's visible plug(s) (ethernet = RJ45); 'unclear' if "
                               "no plug shape is visible.")
    path_visibility: Literal["fully_traced", "partially_visible", "mostly_hidden"]
    connected_port_refs: list[str] = Field(
        description="Ports in THIS image whose plug visibly belongs to this cable (continuous, not inferred)."
    )


class ObservationExtraction(_Strict):
    """Muse Spark structured output for one image."""

    image_usable: bool
    image_issues: list[str]
    shows_inspection_subject: bool = Field(description="False if the photo does not show the specified equipment.")
    scene_summary: str
    devices: list[SeenDevice]
    ports: list[PortObservation]
    cables: list[CableObservation]
    unreadable_details: list[str] = Field(description="Things relevant to the spec that could not be read/seen.")

    @model_validator(mode="after")
    def _refs(self) -> ObservationExtraction:
        dev = {d.ref for d in self.devices}
        ports = {p.ref for p in self.ports}
        if len(dev) != len(self.devices) or len(ports) != len(self.ports):
            raise ValueError("duplicate image-local ref")
        for p in self.ports:
            if p.device_ref not in dev:
                raise ValueError(f"port {p.ref} references unknown device {p.device_ref}")
        for c in self.cables:
            for pr in c.connected_port_refs:
                if pr not in ports:
                    raise ValueError(f"cable {c.ref} references unknown port {pr}")
        return self


CameraAction = Literal[
    "move_closer",
    "move_to_rear",
    "move_to_front",
    "move_left",
    "move_right",
    "look_down_from_above",
    "look_up_from_below",
    "step_back_wide_view",
    "remove_obstruction",
    "improve_lighting",
    "hold_steady_refocus",
]


class NextViewPlan(_Strict):
    """Muse Spark structured output for next-view planning."""

    instruction: str = Field(description="One or two imperative sentences addressed to the camera operator.")
    camera_action: CameraAction
    target_region: str = Field(description="The physical object/region the camera must show.")
    rationale: str
    success_criteria: str = Field(description="What must be visible in the next photo to resolve the gap.")
    visually_resolvable: bool
    unresolvable_reason: str | None

    @field_validator("instruction")
    @classmethod
    def _not_generic(cls, v: str) -> str:
        if len(v.strip()) < 15:
            raise ValueError("instruction too short to be specific")
        return v.strip()
