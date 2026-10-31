"""Muse Spark calls: structured observation extraction and next-view planning."""

from __future__ import annotations

import json

from pydantic import ValidationError

from .evidence import Gap, NextViewRequest
from .images import NormalizedImage
from .meta_client import MetaAPIError, MetaClient
from .observation import CameraAction, NextViewPlan, ObservationExtraction
from .prompts import OBSERVE_SYSTEM, PLAN_SYSTEM, observe_user_text, plan_user_text
from .spec import InspectionSpec
from .wire_schema import wire_schema


class ModelOutputError(RuntimeError):
    pass


def _image_message(text: str, image: NormalizedImage) -> dict:
    return {"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image.data_url()}},
    ]}


async def _structured(client: MetaClient, model_cls, *, system: str, user: dict, image: NormalizedImage,
                      purpose: str, attempts: int = 2):
    """Call Muse with a JSON schema, validate locally, re-ask once with the validation error."""
    messages = [{"role": "system", "content": system}, user]
    last = None
    for i in range(attempts):
        content, _ = await client.chat_structured(messages=messages, schema_name=model_cls.__name__,
                                                  schema=wire_schema(model_cls), image=image,
                                                  purpose=purpose if i == 0 else f"{purpose}.repair")
        try:
            return model_cls.model_validate_json(_strip_fence(content))
        except (ValidationError, ValueError) as e:
            last = e
            client.trace.add("error", f"{purpose}.invalid_output", image_id=image.image_id,
                             error=str(e)[:2000])
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "That output failed validation:\n" + str(e)[:1500]
                 + "\nReturn corrected JSON for the same photo, following the schema exactly."},
            ]
    raise ModelOutputError(f"{purpose}: model output invalid after {attempts} attempts: {last}")


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    return s.strip()


async def extract_observations(client: MetaClient, spec: InspectionSpec,
                               image: NormalizedImage) -> ObservationExtraction:
    ext = await _structured(client, ObservationExtraction, system=OBSERVE_SYSTEM,
                            user=_image_message(observe_user_text(spec), image), image=image,
                            purpose="muse_observe")
    known = {d.id for d in spec.devices}
    for d in ext.devices:
        if d.spec_device_id is not None and d.spec_device_id not in known:
            # Unknown id = not a usable identification; keep the claim but drop the match.
            client.trace.add("policy", "unknown_spec_device_id", image_id=image.image_id,
                             detail={"ref": d.ref, "claimed": d.spec_device_id})
            d.spec_device_id = None
    return ext


_FALLBACK: dict[str, tuple[CameraAction, str]] = {
    "CONTRADICTION": ("move_closer", "Move close to {target} and hold steady so the port, its label and any plug "
                                     "in it are sharp and unobstructed."),
    "DEVICE_NOT_SEEN": ("step_back_wide_view", "Step back and frame the whole {device} ({device_description}) "
                                               "so it is clearly identifiable."),
    "PORTS_NOT_VISIBLE": ("move_to_rear", "Move around to the side of the {device} where its connection ports "
                                          "are, and frame the port row including the printed labels."),
    "LABEL_ILLEGIBLE": ("move_closer", "Move closer to the {device}'s port row so the printed label for "
                                       "{port_label} is readable."),
    "PORT_NOT_FOUND": ("move_closer", "Show the full port row of the {device}, including the port labelled "
                                      "{port_label} and its printed label."),
    "INSERTION_UNCLEAR": ("move_closer", "Move closer to {target} so it is clear whether a plug is fully inserted "
                                         "and what colour it is."),
    "GROUNDING_MISSING": ("move_closer", "Move closer to {target} so the plug and the cable leaving it are both "
                                         "clearly visible and unobstructed."),
    "CABLE_CONTINUITY": ("step_back_wide_view", "Step back so one photo shows {target}, from one device to "
                                                "the other, without the cable being hidden."),
}


_HIDDEN_LABEL = ("move_closer", "The printed label for {port_label} on the {device} appears to be hidden by the "
                                 "inserted plug. Move close and photograph that port row from a low, angled position "
                                 "so the label next to the plug is readable, keeping the neighbouring port labels "
                                 "in the same frame.")


def fallback_plan(gap: Gap, previous_requests: list[str] | None = None) -> NextViewPlan:
    action, tmpl = _HIDDEN_LABEL if gap.context.get("label_hidden_by_plug") else _FALLBACK[gap.code]
    fields = {"target": gap.target, "device": gap.context.get("device", "device"),
              # First clause only: "Black TP-Link Wi-Fi router: glossy ..." -> "Black TP-Link Wi-Fi router"
              "device_description": gap.context.get("device_description", "").split(":")[0].split(".")[0][:80],
              "port_label": gap.context.get("port_label", "")}
    instruction = tmpl.format(**fields)
    if previous_requests:
        instruction += " The previous view did not resolve this; use a different angle or distance than before."
    return NextViewPlan(instruction=instruction, camera_action=action, target_region=gap.target,
                        rationale=gap.missing_fact,
                        success_criteria=f"{gap.target} clearly visible and readable in the next photo.",
                        visually_resolvable=True, unresolvable_reason=None)


async def plan_next_view(client: MetaClient, spec: InspectionSpec, gap: Gap, image: NormalizedImage | None,
                         recent_notes: list[str], request_id: str, *, evidence_state: list[str] | None = None,
                         previous_requests: list[str] | None = None, latest_image_id: str | None = None,
                         ) -> tuple[NextViewRequest, NextViewPlan]:
    plan, planner, err = None, "muse", None
    if image is not None:
        try:
            text = plan_user_text(spec, gap, recent_notes, evidence_state or [], previous_requests or [])
            plan = await _structured(client, NextViewPlan, system=PLAN_SYSTEM,
                                     user=_image_message(text, image),
                                     image=image, purpose="muse_plan")
        except (MetaAPIError, ModelOutputError) as e:
            err = str(e)
    if plan is None:
        plan, planner = fallback_plan(gap, previous_requests), "deterministic_fallback"
    req = NextViewRequest(id=request_id, requirement_id=gap.requirement_id, gap_code=gap.code,
                          missing_fact=gap.missing_fact, target_region=plan.target_region,
                          camera_action=plan.camera_action, instruction=plan.instruction,
                          rationale=plan.rationale, success_criteria=plan.success_criteria,
                          planner=planner, based_on_image_id=image.image_id if image else None,
                          after_image_id=latest_image_id or (image.image_id if image else None),
                          gap_key=gap.key, planner_error=err)
    return req, plan


def summarize_extraction(seq: int, ext: ObservationExtraction | None, err: str | None) -> str:
    if ext is None:
        return f"photo {seq}: extraction failed ({err})"
    devs = ", ".join(f"{d.spec_device_id or 'unknown'}({d.visible_side}, ports_visible={d.ports_visible})"
                     for d in ext.devices) or "no devices"
    return (f"photo {seq}: subject={'yes' if ext.shows_inspection_subject else 'NO'}; {devs}; "
            f"{len(ext.ports)} ports; unreadable: {json.dumps(ext.unreadable_details)}")
