"""Muse Spark calls: structured observation extraction and next-view planning."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from .evidence import Gap, NextViewRequest
from .images import NormalizedImage
from .meta_client import MetaAPIError, MetaClient
from .observation import CameraAction, NextViewPlan, ObservationExtraction
from .prompts import OBSERVE_SYSTEM, PLAN_ASSISTED_RULES, PLAN_SYSTEM, observe_user_text, plan_user_text
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
    # Not used as camera guidance by the agent (a contradiction needs installation review, not another photo).
    "CONTRADICTION": ("hold_steady_refocus", "Check {target} in person: the photos disagree about it. If the "
                                             "installation was changed, declare the change before photographing."),
    "DEVICE_NOT_SEEN": ("step_back_wide_view", "Step back and frame the whole {device} ({device_description}) "
                                               "so it is clearly identifiable."),
    # The ports were already photographed, on a device not identified with certainty in that photo: asking for the
    # same port view again would not help. One photo must tie the identifying features to the ports.
    "DEVICE_UNCONFIRMED": ("look_down_from_above",
                           "Photograph the {device} from a raised, angled position so that the same photo shows both "
                           "its identifying features ({device_description}) and its connection ports. The ports were "
                           "already seen, but not on a device that could be confirmed as the {device}."),
    "PORTS_NOT_VISIBLE": ("move_to_rear", "Move around to the side of the {device} where its connection ports "
                                          "are, and frame the port row including the printed labels."),
    # Neutral about label text: the spec's expected label is a requirement, not something seen in a photo.
    "LABEL_ILLEGIBLE": ("move_closer", "Move closer to the {device}'s port row and photograph it straight on, so "
                                       "that any printed label beside each port can be read and the port expected "
                                       "to be {port_label} can be identified."),
    "PORT_NOT_FOUND": ("move_closer", "Show the {device}'s full port row with every printed label readable, so the "
                                      "port expected to be {port_label} can be identified."),
    "INSERTION_UNCLEAR": ("move_closer", "Move closer to {target} so it is clear whether a plug is fully inserted "
                                         "and what colour it is."),
    "GROUNDING_MISSING": ("move_closer", "From about 20-30 cm, photograph {target} so the plug body and a long "
                                         "stretch of the cable leaving it are both clearly visible and unobstructed, "
                                         "ideally against a plain background."),
    "CABLE_CONTINUITY": ("step_back_wide_view", "Step back so one photo shows {target}, from one device to "
                                                "the other, without the cable being hidden."),
}


_HIDDEN_LABEL = ("move_closer", "A plug is in a {device} port whose printed label could not be read, so it is "
                                 "not yet known whether this is {port_label}. Show a close-up of that occupied port "
                                 "from a low, angled position so that any printed label beside or under the plug can "
                                 "be read, and keep the neighbouring ports' labels in the same frame.")

# --------------------------------------------------------------------------- unread-label presumption guard
# The planner sees the spec's expected label (e.g. 'LAN 1'). Unless that text was actually read in a photo, guidance
# must not present it as visible printed text ("the printed 'LAN 1' text beside its boot"). Naming the target as a
# requirement ("the port labelled LAN 1", "the port expected to be LAN 1") stays allowed.
_PRESUMING_AFTER = re.compile(r"""^\W{0,3}\s*(?:text|label|lettering|marking|markings|print|printing|sticker)\b""",
                              re.IGNORECASE)
_PRESUMING_BEFORE = re.compile(
    r"""\b(?:printed|reads|reading|says|saying|showing|shows|written|engraved|embossed|stamped)\s*['"‘’“”]?\s*$""",
    re.IGNORECASE)


def _label_pattern(label: str) -> re.Pattern[str] | None:
    """Regex for a spec label as text ('LAN 1' ~ 'LAN1' ~ 'lan-1'); bare numbers only when quoted."""
    parts = re.findall(r"[A-Za-z]+|\d+", label)
    if not parts:
        return None
    body = r"[\s\-_]*".join(re.escape(p) for p in parts)
    if all(p.isdigit() for p in parts):
        return re.compile(r"""['"‘’“”]\s*""" + body + r"""\s*['"‘’“”]""")
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.IGNORECASE)


def presumes_unread_label(text: str | None, labels: list[str]) -> bool:
    """True if `text` presents one of `labels` (never read in any photo) as visible printed text."""
    if not text:
        return False
    for label in labels:
        pat = _label_pattern(label)
        if pat is None:
            continue
        for m in pat.finditer(text):
            if _PRESUMING_AFTER.match(text[m.end():m.end() + 24]) or _PRESUMING_BEFORE.search(text[:m.start()]):
                return True
    return False


def _guard_unread_labels(plan: NextViewPlan, gap: Gap, unread_labels: list[str],
                         previous_requests: list[str] | None = None) -> tuple[NextViewPlan, str | None]:
    """Instruction presuming unread label text -> deterministic neutral plan. Other fields -> neutral rewrite.
    A plan judged not visually resolvable is left alone (its instruction is never shown)."""
    if not unread_labels or not plan.visually_resolvable:
        return plan, None
    if presumes_unread_label(plan.instruction, unread_labels):
        return fallback_plan(gap, previous_requests), ("planner instruction presented the expected label as visible text, which no "
                                    "photo has shown; replaced by neutral guidance")
    fixes: dict[str, str] = {}
    if presumes_unread_label(plan.success_criteria, unread_labels):
        fixes["success_criteria"] = (f"The printed label (if any) of the port expected to be "
                                     f"{gap.context.get('port_label', 'the target')} is readable, with the plug in it.")
    if presumes_unread_label(plan.target_region, unread_labels):
        fixes["target_region"] = gap.target
    if presumes_unread_label(plan.rationale, unread_labels):
        fixes["rationale"] = gap.missing_fact
    if not fixes:
        return plan, None
    return plan.model_copy(update=fixes), ("rewrote " + ", ".join(sorted(fixes)) + " that presented the expected "
                                           "label as visible text")


# Assisted templates: a planner instruction that is only a small re-framing of the same view (a few inches/degrees,
# "slightly", a sideways shift) does not name new evidence. It is replaced by the fixed template for the missing fact.
_MICRO = re.compile(r"\b(slightly|a\s+(little|bit|touch|few\s+(inches|centimet\w+|cm|degrees))|"
                    r"\d+(\.\d+)?\s*(-|to)?\s*\d*\s*(inch(es)?|cm|centimet\w+|mm|degrees?)\b|nudge|tilt)", re.I)
_MICRO_ACTIONS = ("move_left", "move_right", "hold_steady_refocus")


def is_micro_adjustment(plan: NextViewPlan) -> bool:
    return plan.camera_action in _MICRO_ACTIONS or bool(_MICRO.search(plan.instruction))


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
                        success_criteria=f"{gap.target} can be identified in the next photo: any printed label "
                                         "beside it readable and any plug in it clearly visible.",
                        visually_resolvable=True, unresolvable_reason=None)


async def plan_next_view(client: MetaClient, spec: InspectionSpec, gap: Gap, image: NormalizedImage | None,
                         recent_notes: list[str], request_id: str, *, evidence_state: list[str] | None = None,
                         previous_requests: list[str] | None = None, latest_image_id: str | None = None,
                         unread_labels: list[str] | None = None,
                         ) -> tuple[NextViewRequest, NextViewPlan]:
    """`unread_labels`: spec labels relevant to this gap that no photo of the current configuration has legibly
    shown. The planner is told so, and its output is checked so it never presents them as visible text."""
    plan, planner, err = None, "muse", None
    unread = list(unread_labels or [])
    if image is not None:
        try:
            text = plan_user_text(spec, gap, recent_notes, evidence_state or [], previous_requests or [],
                                  unread_labels=unread)
            plan = await _structured(client, NextViewPlan,
                                     system=PLAN_SYSTEM + (PLAN_ASSISTED_RULES if spec.assisted else ""),
                                     user=_image_message(text, image),
                                     image=image, purpose="muse_plan")
        except (MetaAPIError, ModelOutputError) as e:
            err = str(e)
    if plan is not None:
        plan, guard_note = _guard_unread_labels(plan, gap, unread, previous_requests)
        if guard_note:
            client.trace.add("plan", "unread_label_guard", detail={"gap": gap.key, "action": guard_note})
            err = guard_note
            if guard_note.startswith("planner instruction"):
                planner = "deterministic_fallback"
    if (plan is not None and spec.assisted is not None and spec.assisted.suppress_micro_adjustments
            and plan.visually_resolvable and is_micro_adjustment(plan)):
        client.trace.add("plan", "micro_adjustment_guard", detail={"gap": gap.key, "instruction": plan.instruction})
        err = f"planner instruction was only a small re-framing ({plan.camera_action}); fixed template used"
        plan = None
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
