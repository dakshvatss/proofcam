# Home Entertainment Installation: three devices, two connections

Status 2026-11-04 (M3.5): **active and loadable** as `data/specs/ps5_home_setup.json`. It is tested with mocked models
only; it has not yet been run on the real hardware with live models.

## The specification
| | |
|---|---|
| Devices | **Wi-Fi Router**: description from the user; no make or model assumed. **PlayStation 5**: original model; rear ports per Sony (LAN, HDMI OUT, 2× USB Type-A, AC IN). **Samsung Television**: description from the user; no model assumed |
| R1 | Ethernet, any colour: router **any LAN port** (printed text in the LAN group; never `WAN` or `Internet`) → PS5 **LAN port** (printed `LAN`/`Ethernet`, or an observed RJ45 socket) |
| R2 | HDMI, any colour: PS5 **HDMI OUT port** (printed `HDMI OUT`/`HDMI`, or an observed HDMI socket) → TV **any HDMI input** (any observed HDMI socket except one labelled `HDMI OUT`) |
| Cable identity | `require_trace` for both: one photo must show the same cable running between both identified ports, SAM-grounded at both |
| Photos | up to 8 (`max_photos`; hard maximum 10). The per-inspection 40-call budget and the server cap still bind |

**Why these port rules, and nothing looser:**
- **Router:** its five RJ45 sockets include an upstream port. Shape cannot tell LAN from WAN, so only legible
  printed text can.
- **PS5:** Sony documents one LAN and one HDMI OUT port, so the spec asserts that the console's Ethernet socket and
  its HDMI socket are those ports.
- **TV:** the user reports three HDMI inputs and no HDMI output, so the spec accepts any HDMI socket on the TV.
- **How shape-based identification is held in check:** it is used only when Muse explicitly reports that socket
  shape, never inferred from the expectation. Every report lists it under "Relies on assumptions".

## How the verdicts come out
- **Each connection** gets its own verdict, evidence, gaps and review state.
- **The installation** is VERIFIED only if both connections are VERIFIED, VIOLATED if either is, and
  INSUFFICIENT_EVIDENCE otherwise.
- **An empty permitted port** (a free LAN port, an unused TV input) is never a violation. A WAN port, an unreadable
  router label, a number without a "LAN" heading, or a socket of unclear shape never qualifies.
- **Practically, R1 will usually end INSUFFICIENT_EVIDENCE** if the Ethernet cable from the wall-mounted router
  cannot be photographed end to end. That is the correct outcome under the cable-identity rule, not a defect.
- **R2 can reach VERIFIED** if one photo shows the HDMI cable from the console's HDMI socket to a TV HDMI input,
  with both plugs clearly inserted and SAM masks at both ports.

## Budget and model calls
- **Per photo:** one Muse observation, SAM for up to 4 concepts, and one Muse plan, so 4–6 calls.
- **SAM cap:** when the per-photo cap would drop concepts, a cable concept is skipped only if no occupied port in
  that photo could use it. Grounding is read only at occupied ports of a compatible connector family.
- **Upper bound:** 8 photos can reach the 40-call per-inspection limit; the inspection then stops honestly
  (`model_call_budget_exhausted`).
- **Defaults unchanged:** no server cap default was changed.

## Run
See [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md). The draft in `data/specs/drafts/` is the earlier placeholder template. It is
kept for history and stays non-loadable.
