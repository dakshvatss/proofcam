# ProofCam inspection: TP-Link router LAN 1 to NETGEAR switch port 3 (blue Ethernet cable)

_ProofCam verifies visually observable conditions only. It does not certify electrical safety, hidden connectivity, operational performance, or regulatory compliance._

_Devices are recognised in each photo by matching them to the spec description; this is not independent proof that photos of a device show the same physical unit. A photo in which more than one device matches the same spec device is not used for it._

Stop reason: `all_requirements_resolved` · photos: 2 · model calls: 9 · est. cost $0.0244

Mode: static verification — all photos of one configuration are assumed to show the same unchanged installation; photo order does not change the assessment.

## Final verdict

### [VERIFIED] R1: The blue Ethernet cable must connect Router LAN 1 to Switch Port 3.

Both endpoints observed with identified ports, clear insertion and matching colour, SAM-grounded (Router LAN 1 from photo 2; Switch 3 from photo 2); cable identity traced in photo 2.

- Endpoint 1 `Router LAN 1`: **established**
  - supports [photo 2 · img_5bba2c69bbbd · direct_label]: Router port P1 'LAN 1' [legible] (cable_inserted, plug=blue, visibility=clear) — grounding: SAM 'blue ethernet cable' mask covers 4392px of the port region
- Endpoint 2 `Switch 3`: **established**
  - supports [photo 2 · img_5bba2c69bbbd · direct_label]: Switch port P2 '3' [legible] (cable_inserted, plug=blue, visibility=clear) — grounding: SAM 'blue ethernet cable' mask covers 5185px of the port region
- Cable identity: **established**
  - [photo 2 · img_5bba2c69bbbd] blue cable C1 traced continuously between Router LAN 1 = P1 (direct_label) and Switch 3 = P2 (direct_label), SAM-grounded at both ports

## Timeline (verdict after each photo)

| # | photo | config | verdict(s) | endpoints | identity | next view / event |
|---|---|---|---|---|---|---|
| 1 | front.jpg | 0 | INSUFFICIENT_EVIDENCE | router LAN 1=unknown; switch 3=unknown | unknown | nv1 |
| 2 | rear.jpg | 0 | VERIFIED | router LAN 1=established; switch 3=established | established | STOP: all_requirements_resolved |

## Investigation (photos in the order received)

### Photo 1 — `img_0f02361ef13a` (front.jpg, 800x600)
Scene: [MOCK] router and switch seen from the front
![overlay](/api/inspections/insp_822cd58814f04a6397c05b37177d76ba/overlays/img_0f02361ef13a)
- SAM `blue ethernet cable`: ok, 1 object(s)
- SAM `network switch`: ok, 0 object(s)
- SAM `router`: ok, 1 object(s)
- Device D1 grounding: best SAM 'router' object 0: box IoU 0.99, Muse box 100% inside its box, mask covers 100% of the Muse box, 99% of the mask inside it, area ratio 1.01 -> corroborated by box IoU (corroborated=True)
- Device D2 grounding: SAM found no 'network switch' (corroborated=False)

Contributes to the final assessment:
- nothing

**Next view `nv1`** (muse, gap `PORTS_NOT_VISIBLE`): [MOCK] Walk around to the back of the router and switch and frame both port rows so the printed labels can be read.
- missing fact: The Router's connection ports have not been visible.
- target: router rear ports · action: `move_to_rear`
- why: ports not visible
- resolves if: The printed label (if any) of the port expected to be LAN 1 is readable, with the plug in it.

### Photo 2 — `img_5bba2c69bbbd` (rear.jpg, 800x600) responding to `nv1`
Scene: [MOCK] rear view, blue cable traced to switch port 3
![overlay](/api/inspections/insp_822cd58814f04a6397c05b37177d76ba/overlays/img_5bba2c69bbbd)
Muse port claims: P1 'LAN 1' [legible] cable_inserted plug=blue (clear); P2 '3' [legible] cable_inserted plug=blue (clear)
- cable C1: blue, fully_traced, ports ['P1', 'P2']
- SAM `blue ethernet cable`: ok, 1 object(s)
- SAM `network switch`: ok, 0 object(s)
- SAM `router`: ok, 1 object(s)
- Device D1 grounding: best SAM 'router' object 0: box IoU 0.99, Muse box 100% inside its box, mask covers 100% of the Muse box, 99% of the mask inside it, area ratio 1.01 -> corroborated by box IoU (corroborated=True)
- Device D2 grounding: SAM found no 'network switch' (corroborated=False)
- Port P1|blue ethernet cable grounding: SAM 'blue ethernet cable' mask covers 4392px of the port region (corroborated=True)
- Port P2|blue ethernet cable grounding: SAM 'blue ethernet cable' mask covers 5185px of the port region (corroborated=True)

Contributes to the final assessment:
- supports Router LAN 1 (direct_label)
- supports Switch 3 (direct_label)
- cable identity: blue cable C1 traced continuously between Router LAN 1 = P1 (direct_label) and Switch 3 = P2 (direct_label), SAM-grounded at both ports

## Model usage

```json
{
  "model_calls": 9,
  "by_model": {
    "muse-spark-1.3": {
      "calls": 3,
      "errors": 0,
      "latency_ms": 13.3283999748528,
      "input_tokens": 4500,
      "output_tokens": 900
    },
    "sam-3.1": {
      "calls": 6,
      "errors": 0,
      "latency_ms": 2292.385800043121,
      "input_tokens": 0,
      "output_tokens": 0
    }
  },
  "estimated_cost_usd": 0.02445
}
```