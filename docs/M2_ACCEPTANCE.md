# Milestone 2 — offline acceptance report (M2.4, 2026-11-03)

**Scope:** M2.1 verdict correctness, M2.2 guidance and contradiction review, M2.3 device grounding geometry, checked
together at `m2-active-agent` HEAD `6755b4f` (code unchanged in M2.4; documentation only).
**Method:** existing automated tests only. Mocked Meta API (`tests/fakes.py`, trace `source="mock"`), offline replay
of recorded live output (`source="replay"`), temporary SQLite databases. **No live or paid calls were made in M2.4.**
No policy, grounding threshold or test was changed.

## Test runs

| Run | Result |
|---|---|
| `pytest -q` (random hash seed) | **351 passed**, 1 live deselected, 162 s |
| `PYTHONHASHSEED=0 pytest -q -rA` | **351 passed**, 1 live deselected, 59 s; 351 PASSED lines, 0 FAILED. The 6 `ERROR` log lines in the captured output come from deliberate fault-injection tests (corrupt stored state, unhandled-error mapping) that pass |

Baseline before M2.4: 351 passed. No regression.

## Criteria

| # | Criterion | Evidence (tests in `backend/tests/`) | Result |
|---|---|---|---|
| 1 | Ambiguous colours cannot cause unsupported verdicts | `test_verdict_correctness`: `test_compare_color` (22 cases), `test_probe_near_colour_is_not_a_violation`, `test_probe_off_white_plug_does_not_violate_a_beige_requirement`, `test_probe_translucent_plug_takes_the_grounded_cable_colour`, `test_cable_colour_association_must_be_sam_grounded_even_in_ablation`, `test_plug_colour_disagreeing_with_its_own_cable_is_uncertain_not_a_violation`; controls `test_clearly_different_colour_still_violates`, `test_empty_target_port_still_violates`, `test_correct_installations_still_verify` | PASS |
| 2 | Conflicting cable traces block VERIFIED | `test_probe_conflicting_trace_is_a_visible_contradiction_not_verified`, `test_conflict_detected_from_either_endpoint`, `test_unique_spec_with_conflicting_trace_is_never_verified`, `test_unqualified_traces_do_not_create_conflicts`, `test_similar_cable_between_other_ports_is_not_joined`, `test_conflicting_trace_without_a_positive_trace_is_reported_not_counted`, `test_conflicting_photo_from_a_superseded_configuration_no_longer_counts`, `test_contradiction_survives_snapshot_and_restore`, `test_conflicting_traces_over_http_report_and_restart` | PASS |
| 3 | Ambiguous device identities block unsupported VERIFIED | `test_probe_two_devices_claiming_one_spec_id_are_not_used`, `test_ambiguous_photo_cannot_establish_a_violation`, `test_unambiguous_photo_still_verifies_and_the_ignored_photo_is_named`, `test_single_device_behaviour_unchanged` | PASS |
| 4 | Contradictions produce review instructions, not futile camera requests | `test_guidance`: `test_probe_p5_endpoint_contradiction_stops_for_review_without_camera_requests`, `test_trace_contradiction_stops_for_review`, `test_other_requirements_continue_while_one_is_blocked`, `test_installation_change_reopens_a_review_stop_and_keeps_history`, `test_review_stop_survives_snapshot_restore_and_json`, `test_review_stop_over_http_with_restart_and_reports` | PASS |
| 5 | Off-target photos do not exhaust specific evidence gaps | `test_probe_p4_unrelated_photos_do_not_exhaust_the_gap_or_replan`, `test_off_target_photos_refund_the_router_attempt`, `test_partial_view_does_not_count_for_a_port_level_gap`, `test_partial_view_does_count_for_the_ports_not_visible_gap`, `test_useful_follow_up_counts_and_closes_the_gap`, `test_attempt_accounting_is_identical_across_restarts`, `test_off_target_photos_over_http_keep_guidance_and_accounting` | PASS |
| 6 | Unread labels are never presented as observed facts in user-facing **mocked** guidance | `test_guard_flags_unread_label_presented_as_visible_text`, `test_guard_allows_wording_that_only_names_the_target`, `test_every_deterministic_template_is_neutral_about_label_text`, `test_presumptuous_live_instruction_is_replaced_by_neutral_guidance` (the recorded live smoke-test wording), `test_presumptuous_success_criteria_rewritten_but_muse_instruction_kept`, `test_guard_is_off_once_the_label_has_actually_been_read`, `test_unresolvable_plan_is_not_overridden_by_the_guard` | PASS (mocked only; see R1) |
| 7 | Device corroboration handles antenna-shaped masks | `test_grounding_geometry`: `test_router_with_antennas_is_corroborated_by_containment_not_iou`, `test_link_devices_end_to_end_with_antenna_mask`, guards `test_oversized_mask_does_not_corroborate`, `test_displaced_mask_does_not_corroborate`, `test_sparse_mask_inside_a_large_box_is_a_near_miss`, `test_partially_contained_box_is_a_near_miss`, `test_each_object_is_judged_alone_a_different_object_never_counts`, `test_higher_iou_wrong_object_does_not_hide_the_contained_one`; `test_device_links_never_change_a_verdict`, `test_antenna_mask_over_http_report_and_unchanged_verdict` | PASS |
| 8 | Port-level grounding limitations remain documented | Executable documentation: `test_cable_mask_at_one_port_also_reaches_the_expanded_region_of_its_neighbour`, `test_policy_does_not_let_a_neighbouring_mask_turn_an_empty_port_into_support`. Written: DECISIONS D32, GUIDE §5 (`link_ports`), README §2, this report R2 | PASS |
| 9 | SQLite restart, FastAPI compatibility, idempotency, model-call accounting intact | `test_acceptance`: `test_verdicts_over_http_with_restart_between_photos_match_direct_m0`, `test_photo_order_independence_over_http`, `test_budget_exhaustion_survives_restarts_without_reset`, `test_every_http_attempt_is_reserved_first_including_retries`, `test_server_shutdown_mid_step_then_restart_and_retry`, `test_real_process_kill_mid_step_is_recovered_and_counted_once`, `test_idempotency_matrix_across_restart_and_inspections`, `test_commit_failure_rolls_back_and_the_retry_succeeds`, `test_version_conflict_is_refused_and_nothing_is_saved`, `test_no_secrets_databases_or_private_images_are_tracked`; `test_api`: `test_idempotency_over_http`, `test_stale_guidance_and_stopped_inspection_are_409`, `test_concurrent_capture_gets_409_busy`; `test_guidance`: `test_old_stored_step_response_without_the_new_field_still_validates`; `test_grounding_geometry`: `test_grounding_link_schema_unchanged_for_stored_records`; plus `test_store`, `test_service`, `test_persistence` | PASS |
| 10 | Historical inspections are flagged, never rewritten | `test_old_verdicts_are_flagged_not_rewritten` (M1-stored verdict → `policy_drift` + `engine_changed`, stored verdict unchanged) | PASS |

**Milestone 2 offline acceptance: PASS (10/10).** Live validation of the M2 changes was out of scope by decision
(D33).

## Unresolved risks (carried to M3–M5)

| # | Risk | Status / mitigation |
|---|---|---|
| R1 | **No live guidance validation since M2.2.** Muse has not been called with the new planner prompt. | The deterministic guard (D28) replaces any instruction that presents an unread label as printed text, so this cannot reach users in the guarded forms tested; wording outside the guard's patterns, and how often Muse triggers it, are unmeasured. Proposed capped check (≈ 8 planner calls, ≤ $0.10) not run. |
| R2 | **Adjacent same-colour cables are ambiguous.** SAM port grounding is presence near a port; in 10 of 14 recorded occupied ports the mask also reached an empty neighbour (D32). Muse port boxes are ~½–1 port off. | Port identity and occupancy rest on Muse's per-port claims plus M2.1 rules; a legibly empty port stays a violation. SAM port/plug concept measurement (15 calls, ≈ $0.04) proposed, not run. |
| R3 | **Cross-photo physical identity is not independently proven.** Devices are matched per photo to the spec description; cable identity across photos is joined only through port identity under the static-installation assumption; `unique_in_installation` is an author assertion. | Disclosed in every report (`device_identity_note`) and in assumptions. |
| R4 | **Not deployable publicly.** No API authentication, no spending cap across inspections (only 40 calls per inspection), synchronous captures (25–48 s observed; ≈ 19 min theoretical worst case), upload limit enforced only after receipt. | Must be resolved before M5 (D24). Local/demo use only. |
| R5 | **Historical policy drift.** `engine_version` hashes the bytes of 10 engine modules; any edit marks every stored inspection `engine_changed`, and inspections whose stored assessment the current policy would not reproduce show `policy_drift`. | By design: stored verdicts are never recomputed; the API and reports flag them. The frontend should show a banner. |
| R6 | On the user's real setup the plug hides both target labels: `label_only` cannot verify from real photos. | Correct abstention; affects the demo. The only live VERIFIED used an AI-generated photo and must not be presented as real-installation validation. |
| R7 | SAM `network switch` returns 0 objects on the user's switch. | Report-only; no verdict uses device links. |
| R8 | No CORS configuration in the API. | The M3 app must be served same-origin or through a dev proxy (FRONTEND_HANDOFF). |
