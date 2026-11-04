"""SQLite persistence for inspections (Milestone 1). Standard-library sqlite3 only.

One source of truth per fact; an AgentState is REBUILT from these tables, never stored as a second copy:

  inspections         spec, control state (gap attempts, exhausted gaps, current assessments, stop reason, epoch,
                      budget), authoritative model-call counter, version, lease
  photos              normalized JPEG + stored overlay (BLOBs; restored byte-for-byte, never re-encoded)
  observations        append-only evidence (ObservationRecord JSON)
  next_view_requests  append-only
  steps               append-only agent history + the assessment snapshot after each step
  trace_events        append-only audit trace (contiguous seq 0..n-1)
  submissions         idempotency key -> image identity, status, stored response, failure audit
  model_calls         one row per model call, written BEFORE the call is sent (budget + audit)

Model-call accounting: `reserve_model_call` increments the inspection's counter and inserts a `reserved` row in one
transaction before a call goes out; the counter only ever grows there. A crash leaves the row `reserved`; recovery
relabels it `outcome_unknown` (it may or may not have been billed) without changing the counter, so nothing is
charged twice and nothing invented. `commit_step` sets the counter to max(stored, agent's count), never a sum.
`load_restore_bundle` hands the authoritative counter to InspectionAgent.restore().

The store never receives Settings (no API key) and refuses trace content that carries image data or bearer tokens.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from . import __version__
from .agent import AgentState, StopReason
from .evidence import NextViewRequest, ObservationRecord, OperatorDeclaration, RequirementAssessment
from .images import ImageLoadError, NormalizedImage
from .spec import InspectionSpec
from .trace import TraceEvent

SubmissionStatus = Literal["processing", "done", "failed", "interrupted"]
CallStatus = Literal["reserved", "ok", "error", "outcome_unknown"]


# ---------------------------------------------------------------------------- errors

class StoreError(RuntimeError):
    """Base class for controlled storage errors."""


class StoreCorruptionError(StoreError):
    """The database file or a stored record is unreadable or inconsistent."""


class SchemaVersionError(StoreError):
    pass


class InspectionNotFound(StoreError):
    pass


class InspectionExists(StoreError):
    pass


class InspectionBusy(StoreError):
    """Another operation holds the inspection's lease (Stage 3 maps this to HTTP 409)."""

    def __init__(self, message: str, since: float | None = None) -> None:
        super().__init__(message)
        self.since = since


class LeaseLost(StoreError):
    """The caller's lease token is not (or no longer) the inspection's lease."""


class VersionConflict(StoreError):
    """The inspection changed since the caller loaded it (stale write)."""


class AppendOnlyViolation(StoreError):
    """A commit would rewrite or drop already-stored evidence, history, requests or trace."""


class IdempotencyConflict(StoreError):
    """An idempotency key was reused with different image content."""


class ModelCallBudgetExhausted(StoreError):
    pass


class UnsafeContent(StoreError):
    """Content that must never be persisted (image data URLs, bearer tokens)."""


# ---------------------------------------------------------------------------- records

@dataclass(frozen=True)
class InspectionRecord:
    id: str
    spec_id: str | None
    title: str
    status: Literal["open", "stopped"]
    stop_reason: str | None
    epoch: int
    version: int
    engine_version: str
    model_call_limit: int
    model_calls_reserved: int
    lease_token: str | None
    lease_acquired_at: float | None
    lease_heartbeat_at: float | None
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class RestoreBundle:
    """Everything InspectionAgent.restore() needs:

        client = MetaClient(settings, Trace.from_events(b.trace_events), ...)
        agent = InspectionAgent.restore(b.state, client, settings, b.images)

    b.state.model_calls_started is the authoritative stored counter (includes calls reserved by interrupted
    attempts), not the count of the last committed snapshot.
    """

    record: InspectionRecord
    state: AgentState
    trace_events: list[TraceEvent]
    images: list[NormalizedImage]

    @property
    def version(self) -> int:
        return self.record.version


@dataclass(frozen=True)
class StepSnapshot:
    step_no: int
    kind: Literal["photo", "duplicate", "installation_changed"]
    history: dict[str, Any]
    assessments: list[RequirementAssessment]
    created_at: float


@dataclass(frozen=True)
class Submission:
    inspection_id: str
    idempotency_key: str
    image_id: str
    status: SubmissionStatus
    attempts: int
    lease_token: str | None
    response: dict[str, Any] | None
    failures: list[dict[str, Any]]
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class CaptureStarted:
    """A new attempt may run: the caller holds `lease_token` and must end with commit_step or fail_submission."""

    lease_token: str
    attempt: int
    version: int


@dataclass(frozen=True)
class CaptureCompleted:
    """The key already completed: return the stored response; no new step."""

    response: dict[str, Any]


@dataclass(frozen=True)
class ModelCallRecord:
    ordinal: int
    name: str
    image_id: str | None
    idempotency_key: str | None
    attempt: int | None
    status: CallStatus
    reserved_at: float
    settled_at: float | None
    detail: dict[str, Any] | None


@dataclass(frozen=True)
class RecoveryReport:
    inspection_id: str
    lease_token: str
    interrupted_submissions: list[str]
    unknown_outcome_calls: list[int]


class _Control(BaseModel):
    """Inspection control state not held in an append-only table."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    require_grounding: bool
    plan_with_muse: bool
    budget: dict[str, int]
    gap_attempts: dict[str, int]
    exhausted: dict[str, str]
    assessments: list[RequirementAssessment]
    stop_reason: StopReason | None
    # Operator declarations (M3.7), append-only like the evidence; absent from earlier rows (= none).
    declarations: list[OperatorDeclaration] = []


# ---------------------------------------------------------------------------- schema

SCHEMA_VERSION = 1

# (version, statements). Each migration runs in one transaction together with its PRAGMA user_version bump.
MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        """CREATE TABLE inspections (
            id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 128),
            spec_id TEXT,
            title TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            control_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('open', 'stopped')),
            stop_reason TEXT,
            epoch INTEGER NOT NULL CHECK (epoch >= 0),
            model_call_limit INTEGER NOT NULL CHECK (model_call_limit >= 0),
            model_calls_reserved INTEGER NOT NULL DEFAULT 0 CHECK (model_calls_reserved >= 0),
            version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
            engine_version TEXT NOT NULL,
            lease_token TEXT,
            lease_acquired_at REAL,
            lease_heartbeat_at REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            CHECK ((lease_token IS NULL) = (lease_acquired_at IS NULL)),
            CHECK ((lease_token IS NULL) = (lease_heartbeat_at IS NULL)),
            CHECK ((status = 'stopped') = (stop_reason IS NOT NULL))
        )""",
        "CREATE INDEX ix_inspections_lease ON inspections (lease_heartbeat_at) WHERE lease_token IS NOT NULL",
        """CREATE TABLE photos (
            inspection_id TEXT NOT NULL REFERENCES inspections (id),
            image_id TEXT NOT NULL CHECK (image_id GLOB 'img_*'),
            source_name TEXT NOT NULL,
            width INTEGER NOT NULL CHECK (width > 0),
            height INTEGER NOT NULL CHECK (height > 0),
            orig_width INTEGER NOT NULL CHECK (orig_width > 0),
            orig_height INTEGER NOT NULL CHECK (orig_height > 0),
            jpeg BLOB NOT NULL CHECK (length(jpeg) > 0),
            overlay_jpeg BLOB,
            created_at REAL NOT NULL,
            PRIMARY KEY (inspection_id, image_id)
        )""",
        """CREATE TABLE observations (
            inspection_id TEXT NOT NULL REFERENCES inspections (id),
            seq INTEGER NOT NULL CHECK (seq >= 1),
            image_id TEXT NOT NULL,
            epoch INTEGER NOT NULL CHECK (epoch >= 0),
            responding_to TEXT,
            record_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (inspection_id, seq),
            UNIQUE (inspection_id, image_id),
            FOREIGN KEY (inspection_id, image_id) REFERENCES photos (inspection_id, image_id)
        )""",
        """CREATE TABLE next_view_requests (
            inspection_id TEXT NOT NULL REFERENCES inspections (id),
            ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
            request_id TEXT NOT NULL,
            after_image_id TEXT,
            gap_key TEXT,
            request_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (inspection_id, ordinal),
            UNIQUE (inspection_id, request_id)
        )""",
        """CREATE TABLE steps (
            inspection_id TEXT NOT NULL REFERENCES inspections (id),
            step_no INTEGER NOT NULL CHECK (step_no >= 1),
            kind TEXT NOT NULL CHECK (kind IN ('photo', 'duplicate', 'installation_changed')),
            history_json TEXT NOT NULL,
            assessments_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (inspection_id, step_no)
        )""",
        """CREATE TABLE trace_events (
            inspection_id TEXT NOT NULL REFERENCES inspections (id),
            seq INTEGER NOT NULL CHECK (seq >= 0),
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('live', 'mock', 'replay', 'local')),
            event_json TEXT NOT NULL,
            PRIMARY KEY (inspection_id, seq)
        )""",
        """CREATE TABLE submissions (
            inspection_id TEXT NOT NULL REFERENCES inspections (id),
            idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
            image_id TEXT NOT NULL CHECK (image_id GLOB 'img_*'),
            status TEXT NOT NULL CHECK (status IN ('processing', 'done', 'failed', 'interrupted')),
            attempts INTEGER NOT NULL CHECK (attempts >= 1),
            lease_token TEXT,
            response_json TEXT,
            failures_json TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (inspection_id, idempotency_key),
            CHECK ((status = 'done') = (response_json IS NOT NULL))
        )""",
        "CREATE INDEX ix_submissions_status ON submissions (inspection_id, status)",
        """CREATE TABLE model_calls (
            inspection_id TEXT NOT NULL REFERENCES inspections (id),
            ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
            lease_token TEXT NOT NULL,
            idempotency_key TEXT,
            attempt INTEGER,
            name TEXT NOT NULL,
            image_id TEXT,
            status TEXT NOT NULL CHECK (status IN ('reserved', 'ok', 'error', 'outcome_unknown')),
            reserved_at REAL NOT NULL,
            settled_at REAL,
            detail_json TEXT,
            PRIMARY KEY (inspection_id, ordinal)
        )""",
        "CREATE INDEX ix_model_calls_lease ON model_calls (inspection_id, lease_token, status)",
    ]),
]

_ENGINE_FILES = ("agent.py", "policy.py", "evidence.py", "grounding.py", "geometry.py", "muse.py", "prompts.py",
                 "observation.py", "spec.py", "wire_schema.py")


def engine_version() -> str:
    """Package version + fingerprint of the modules that decide verdicts and guidance (for policy-drift audit)."""
    h = hashlib.sha256()
    for name in _ENGINE_FILES:
        h.update((Path(__file__).parent / name).read_bytes())
    return f"{__version__}+{h.hexdigest()[:12]}"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _step_kind(entry: dict[str, Any]) -> str:
    if entry.get("event") == "installation_changed":
        return "installation_changed"
    return "duplicate" if entry.get("duplicate_of") is not None else "photo"


_UNSAFE_MARKERS = ("data:image/", "bearer ")


def _check_safe(text: str, where: str) -> None:
    low = text.lower()
    for m in _UNSAFE_MARKERS:
        if m in low:
            raise UnsafeContent(f"{where} contains '{m.strip()}' content, which must never be stored")


# ---------------------------------------------------------------------------- store

class Store:
    """Thread-safe (one connection, serialized by a lock). Several Store objects / processes may share a file:
    writes use BEGIN IMMEDIATE, leases are conditional updates, commits check the version."""

    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time,
                 busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        try:
            self._conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
            self._conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
            mode = self._conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise StoreError(f"could not enable WAL mode (got {mode})")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._migrate()
        except sqlite3.DatabaseError as e:
            self._close_quietly()
            raise StoreCorruptionError(f"{self.path}: not a usable ProofCam database ({e})") from e
        except StoreError:
            self._close_quietly()
            raise

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _close_quietly(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        with self._lock:
            return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    def check_integrity(self) -> list[str]:
        """SQLite integrity + foreign-key check; empty list means healthy."""
        with self._lock:
            problems = [r[0] for r in self._conn.execute("PRAGMA integrity_check") if r[0] != "ok"]
            problems += [f"foreign key violation in {r[0]} rowid {r[1]}"
                         for r in self._conn.execute("PRAGMA foreign_key_check")]
            return problems

    def _migrate(self) -> None:
        current = self.schema_version
        latest = max(v for v, _ in MIGRATIONS)
        if current > latest:
            raise SchemaVersionError(f"{self.path}: schema version {current} is newer than this code ({latest})")
        for version, statements in MIGRATIONS:
            if version <= current:
                continue
            try:
                with self._tx() as c:
                    for stmt in statements:
                        c.execute(stmt)
                    c.execute(f"PRAGMA user_version = {int(version)}")
            except sqlite3.DatabaseError as e:
                raise SchemaVersionError(f"{self.path}: migration to schema {version} failed and was rolled "
                                         f"back: {e}") from e

    @contextmanager
    def _tx(self, write: bool = True) -> Iterator[sqlite3.Connection]:
        """Explicit transaction: COMMIT on success, ROLLBACK on any exception (then re-raised)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _loads(text: str | None, what: str) -> Any:
        if text is None:
            return None
        try:
            return json.loads(text)
        except (TypeError, ValueError) as e:
            raise StoreCorruptionError(f"stored {what} is not valid JSON: {e}") from e

    @staticmethod
    def _record(row: sqlite3.Row | tuple) -> InspectionRecord:
        return InspectionRecord(*row)

    _RECORD_COLS = ("id, spec_id, title, status, stop_reason, epoch, version, engine_version, model_call_limit, "
                    "model_calls_reserved, lease_token, lease_acquired_at, lease_heartbeat_at, created_at, updated_at")

    def _get(self, c: sqlite3.Connection, inspection_id: str) -> InspectionRecord:
        row = c.execute(f"SELECT {self._RECORD_COLS} FROM inspections WHERE id = ?", (inspection_id,)).fetchone()
        if row is None:
            raise InspectionNotFound(f"inspection {inspection_id} not found")
        return self._record(row)

    def _require_lease(self, c: sqlite3.Connection, inspection_id: str, token: str) -> InspectionRecord:
        rec = self._get(c, inspection_id)
        if rec.lease_token is None or rec.lease_token != token:
            raise LeaseLost(f"inspection {inspection_id}: lease {token[:8]}... is not held")
        return rec

    def _unknown_calls(self, c: sqlite3.Connection, inspection_id: str, token: str, now: float) -> list[int]:
        """Calls reserved under this lease whose outcome was never recorded. Counter untouched (already counted)."""
        ords = [r[0] for r in c.execute(
            "SELECT ordinal FROM model_calls WHERE inspection_id = ? AND lease_token = ? AND status = 'reserved' "
            "ORDER BY ordinal", (inspection_id, token))]
        c.execute("UPDATE model_calls SET status = 'outcome_unknown', settled_at = ? "
                  "WHERE inspection_id = ? AND lease_token = ? AND status = 'reserved'", (now, inspection_id, token))
        return ords

    # ------------------------------------------------------------------ inspections

    def create_inspection(self, inspection_id: str, state: AgentState, *, spec_id: str | None = None,
                          engine: str | None = None) -> InspectionRecord:
        """Create from the snapshot of a fresh agent (no photos, no requests, no history, no calls, no trace)."""
        if (state.observations or state.requests or state.history or state.trace_event_count
                or state.model_calls_started or state.assessments or state.epoch or state.stop_reason):
            raise StoreError("create_inspection needs the snapshot of a fresh agent")
        now = self._clock()
        control = _Control(require_grounding=state.require_grounding, plan_with_muse=state.plan_with_muse,
                           budget=state.budget, gap_attempts={}, exhausted={}, assessments=[], stop_reason=None)
        try:
            with self._tx() as c:
                c.execute(
                    "INSERT INTO inspections (id, spec_id, title, spec_json, control_json, status, stop_reason, epoch, "
                    "model_call_limit, model_calls_reserved, version, engine_version, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'open', NULL, 0, ?, 0, 0, ?, ?, ?)",
                    (inspection_id, spec_id, state.spec.title, state.spec.model_dump_json(),
                     control.model_dump_json(), state.model_call_limit, engine or engine_version(), now, now))
                return self._get(c, inspection_id)
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e) or "PRIMARY KEY" in str(e):
                raise InspectionExists(f"inspection {inspection_id} already exists") from e
            raise StoreError(f"invalid inspection record: {e}") from e

    def get_inspection(self, inspection_id: str) -> InspectionRecord:
        with self._tx(write=False) as c:
            return self._get(c, inspection_id)

    def load_restore_bundle(self, inspection_id: str) -> RestoreBundle:
        """Read everything needed to rebuild the agent, in one consistent read transaction."""
        with self._tx(write=False) as c:
            rec = self._get(c, inspection_id)
            spec_json, control_json = c.execute(
                "SELECT spec_json, control_json FROM inspections WHERE id = ?", (inspection_id,)).fetchone()
            obs = [r[0] for r in c.execute(
                "SELECT record_json FROM observations WHERE inspection_id = ? ORDER BY seq", (inspection_id,))]
            reqs = [r[0] for r in c.execute(
                "SELECT request_json FROM next_view_requests WHERE inspection_id = ? ORDER BY ordinal",
                (inspection_id,))]
            hist = [r[0] for r in c.execute(
                "SELECT history_json FROM steps WHERE inspection_id = ? ORDER BY step_no", (inspection_id,))]
            trace = [r[0] for r in c.execute(
                "SELECT event_json FROM trace_events WHERE inspection_id = ? ORDER BY seq", (inspection_id,))]
            photos = c.execute(
                "SELECT image_id, source_name, width, height, orig_width, orig_height, jpeg FROM photos "
                "WHERE inspection_id = ? ORDER BY created_at, image_id", (inspection_id,)).fetchall()
        try:
            control = _Control.model_validate_json(control_json)
            state = AgentState(
                spec=InspectionSpec.model_validate_json(spec_json),
                require_grounding=control.require_grounding, plan_with_muse=control.plan_with_muse,
                budget=control.budget,
                observations=[ObservationRecord.model_validate_json(x) for x in obs],
                requests=[NextViewRequest.model_validate_json(x) for x in reqs],
                gap_attempts=control.gap_attempts, exhausted=control.exhausted, assessments=control.assessments,
                stop_reason=control.stop_reason, epoch=rec.epoch, declarations=control.declarations,
                history=[self._loads(x, "history entry") for x in hist],
                model_calls_started=rec.model_calls_reserved, model_call_limit=rec.model_call_limit,
                trace_event_count=len(trace))
            events = [TraceEvent.model_validate_json(x) for x in trace]
            images = [NormalizedImage.from_stored(i, n, w, h, bytes(b), (ow, oh))
                      for i, n, w, h, ow, oh, b in photos]
        except (ValidationError, ImageLoadError) as e:
            raise StoreCorruptionError(f"inspection {inspection_id}: stored record is invalid: {e}") from e
        if [e.seq for e in events] != list(range(len(events))):
            raise StoreCorruptionError(f"inspection {inspection_id}: trace sequence is not contiguous")
        if [o.seq for o in state.observations] != list(range(1, len(state.observations) + 1)):
            raise StoreCorruptionError(f"inspection {inspection_id}: observation sequence is not contiguous")
        return RestoreBundle(rec, state, events, images)

    def load_assessments(self, inspection_id: str) -> list[RequirementAssessment]:
        """Current requirement assessments (as last committed by the deterministic policy)."""
        with self._tx(write=False) as c:
            self._get(c, inspection_id)
            (control_json,) = c.execute("SELECT control_json FROM inspections WHERE id = ?",
                                        (inspection_id,)).fetchone()
        try:
            return _Control.model_validate_json(control_json).assessments
        except ValidationError as e:
            raise StoreCorruptionError(f"inspection {inspection_id}: control state is invalid: {e}") from e

    def load_steps(self, inspection_id: str) -> list[StepSnapshot]:
        """Per-step history with the assessments as they stood after that step."""
        with self._tx(write=False) as c:
            self._get(c, inspection_id)
            rows = c.execute("SELECT step_no, kind, history_json, assessments_json, created_at FROM steps "
                             "WHERE inspection_id = ? ORDER BY step_no", (inspection_id,)).fetchall()
        try:
            return [StepSnapshot(n, k, self._loads(h, "history entry"),
                                 [RequirementAssessment.model_validate(a) for a in self._loads(a, "assessments")],
                                 t) for n, k, h, a, t in rows]
        except ValidationError as e:
            raise StoreCorruptionError(f"inspection {inspection_id}: stored assessments are invalid: {e}") from e

    # ------------------------------------------------------------------ photos / overlays

    def load_photo(self, inspection_id: str, image_id: str) -> NormalizedImage:
        with self._tx(write=False) as c:
            row = c.execute("SELECT source_name, width, height, orig_width, orig_height, jpeg FROM photos "
                            "WHERE inspection_id = ? AND image_id = ?", (inspection_id, image_id)).fetchone()
        if row is None:
            raise StoreError(f"photo {image_id} not found in inspection {inspection_id}")
        n, w, h, ow, oh, b = row
        try:
            return NormalizedImage.from_stored(image_id, n, w, h, bytes(b), (ow, oh))
        except ImageLoadError as e:
            raise StoreCorruptionError(str(e)) from e

    def load_overlay(self, inspection_id: str, image_id: str) -> bytes | None:
        with self._tx(write=False) as c:
            row = c.execute("SELECT overlay_jpeg FROM photos WHERE inspection_id = ? AND image_id = ?",
                            (inspection_id, image_id)).fetchone()
        if row is None:
            raise StoreError(f"photo {image_id} not found in inspection {inspection_id}")
        return bytes(row[0]) if row[0] is not None else None

    def load_overlays(self, inspection_id: str) -> dict[str, bytes]:
        with self._tx(write=False) as c:
            rows = c.execute("SELECT image_id, overlay_jpeg FROM photos WHERE inspection_id = ? "
                             "AND overlay_jpeg IS NOT NULL", (inspection_id,)).fetchall()
        return {i: bytes(b) for i, b in rows}

    def save_overlay(self, inspection_id: str, lease_token: str, image_id: str, jpeg: bytes) -> None:
        if not jpeg:
            raise StoreError("empty overlay")
        with self._tx() as c:
            self._require_lease(c, inspection_id, lease_token)
            n = c.execute("UPDATE photos SET overlay_jpeg = ? WHERE inspection_id = ? AND image_id = ?",
                          (jpeg, inspection_id, image_id)).rowcount
            if n != 1:
                raise StoreError(f"photo {image_id} not found in inspection {inspection_id}")

    # ------------------------------------------------------------------ leases

    def acquire_lease(self, inspection_id: str) -> str:
        """Atomically take the inspection's lease; raises InspectionBusy if anyone holds it (even a stale holder:
        stale leases are cleared only by recover_interrupted)."""
        token = uuid.uuid4().hex
        now = self._clock()
        with self._tx() as c:
            rec = self._get(c, inspection_id)
            n = c.execute("UPDATE inspections SET lease_token = ?, lease_acquired_at = ?, lease_heartbeat_at = ? "
                          "WHERE id = ? AND lease_token IS NULL", (token, now, now, inspection_id)).rowcount
            if n != 1:
                raise InspectionBusy(f"inspection {inspection_id} is busy", since=rec.lease_acquired_at)
        return token

    def renew_lease(self, inspection_id: str, lease_token: str) -> None:
        with self._tx() as c:
            self._require_lease(c, inspection_id, lease_token)
            c.execute("UPDATE inspections SET lease_heartbeat_at = ? WHERE id = ?", (self._clock(), inspection_id))

    def release_lease(self, inspection_id: str, lease_token: str) -> None:
        """Release a lease taken with acquire_lease (no capture in progress). Capture attempts end with
        commit_step or fail_submission instead, so their submission status is never left 'processing'."""
        with self._tx() as c:
            self._require_lease(c, inspection_id, lease_token)
            if c.execute("SELECT 1 FROM submissions WHERE inspection_id = ? AND lease_token = ? "
                         "AND status = 'processing'", (inspection_id, lease_token)).fetchone():
                raise StoreError("a capture is in progress under this lease; use commit_step or fail_submission")
            self._unknown_calls(c, inspection_id, lease_token, self._clock())
            c.execute("UPDATE inspections SET lease_token = NULL, lease_acquired_at = NULL, "
                      "lease_heartbeat_at = NULL WHERE id = ?", (inspection_id,))

    def recover_interrupted(self, stale_before: float) -> list[RecoveryReport]:
        """Clear leases whose last heartbeat is older than `stale_before` (pass the current time at startup of a
        single-process server; a threshold above the longest possible step otherwise).

        Per lease: 'processing' submissions -> 'interrupted' (attempt kept in the failure audit); 'reserved' model
        calls -> 'outcome_unknown'; lease cleared. The call counter is NOT changed: reserved calls were counted
        once when reserved. Idempotent: a second run finds nothing to do.
        """
        with self._tx(write=False) as c:
            stale = c.execute("SELECT id, lease_token FROM inspections WHERE lease_token IS NOT NULL "
                              "AND lease_heartbeat_at < ?", (stale_before,)).fetchall()
        reports = []
        for inspection_id, token in stale:
            now = self._clock()
            with self._tx() as c:
                # Re-check inside the write transaction: the holder may have finished or renewed meanwhile.
                n = c.execute("UPDATE inspections SET lease_token = NULL, lease_acquired_at = NULL, "
                              "lease_heartbeat_at = NULL WHERE id = ? AND lease_token = ? AND lease_heartbeat_at < ?",
                              (inspection_id, token, stale_before)).rowcount
                if n != 1:
                    continue
                keys = []
                for key, attempts, failures in c.execute(
                        "SELECT idempotency_key, attempts, failures_json FROM submissions WHERE inspection_id = ? "
                        "AND lease_token = ? AND status = 'processing'", (inspection_id, token)).fetchall():
                    f = self._loads(failures, "failure audit") + [
                        {"attempt": attempts, "status": "interrupted", "at": now,
                         "error": "lease recovered after an interruption; the attempt's outcome was not committed"}]
                    c.execute("UPDATE submissions SET status = 'interrupted', failures_json = ?, updated_at = ? "
                              "WHERE inspection_id = ? AND idempotency_key = ?",
                              (_canonical(f), now, inspection_id, key))
                    keys.append(key)
                calls = self._unknown_calls(c, inspection_id, token, now)
            reports.append(RecoveryReport(inspection_id, token, keys, calls))
        return reports

    # ------------------------------------------------------------------ submissions / idempotency

    def begin_capture(self, inspection_id: str, idempotency_key: str, image_id: str
                      ) -> CaptureStarted | CaptureCompleted:
        """Start (or retry) a capture attempt, atomically with taking the lease.

        Same key + same image: 'done' -> CaptureCompleted (stored response, no new step); 'processing' ->
        InspectionBusy; 'failed'/'interrupted' -> a new attempt. Same key + different image -> IdempotencyConflict.
        """
        token = uuid.uuid4().hex
        now = self._clock()
        with self._tx() as c:
            rec = self._get(c, inspection_id)
            row = c.execute("SELECT image_id, status, attempts, response_json FROM submissions "
                            "WHERE inspection_id = ? AND idempotency_key = ?",
                            (inspection_id, idempotency_key)).fetchone()
            if row is not None:
                prev_image, status, attempts, response = row
                if prev_image != image_id:
                    raise IdempotencyConflict(f"idempotency key {idempotency_key!r} was used for image {prev_image}, "
                                              f"not {image_id}")
                if status == "done":
                    return CaptureCompleted(self._loads(response, "submission response"))
                if status == "processing":
                    raise InspectionBusy(f"submission {idempotency_key!r} is still processing",
                                         since=rec.lease_acquired_at)
            n = c.execute("UPDATE inspections SET lease_token = ?, lease_acquired_at = ?, lease_heartbeat_at = ? "
                          "WHERE id = ? AND lease_token IS NULL", (token, now, now, inspection_id)).rowcount
            if n != 1:
                raise InspectionBusy(f"inspection {inspection_id} is busy", since=rec.lease_acquired_at)
            if row is None:
                attempt = 1
                c.execute("INSERT INTO submissions (inspection_id, idempotency_key, image_id, status, attempts, "
                          "lease_token, created_at, updated_at) VALUES (?, ?, ?, 'processing', 1, ?, ?, ?)",
                          (inspection_id, idempotency_key, image_id, token, now, now))
            else:
                attempt = row[2] + 1
                c.execute("UPDATE submissions SET status = 'processing', attempts = ?, lease_token = ?, "
                          "updated_at = ? WHERE inspection_id = ? AND idempotency_key = ?",
                          (attempt, token, now, inspection_id, idempotency_key))
            return CaptureStarted(token, attempt, rec.version)

    def get_submission(self, inspection_id: str, idempotency_key: str) -> Submission | None:
        with self._tx(write=False) as c:
            row = c.execute("SELECT inspection_id, idempotency_key, image_id, status, attempts, lease_token, "
                            "response_json, failures_json, created_at, updated_at FROM submissions "
                            "WHERE inspection_id = ? AND idempotency_key = ?",
                            (inspection_id, idempotency_key)).fetchone()
        if row is None:
            return None
        i, k, img, st, att, tok, resp, fails, ca, ua = row
        return Submission(i, k, img, st, att, tok, self._loads(resp, "submission response"),
                          self._loads(fails, "failure audit"), ca, ua)

    def fail_submission(self, inspection_id: str, lease_token: str, idempotency_key: str, error: str,
                        detail: dict[str, Any] | None = None) -> None:
        """End an attempt without a step: nothing of the attempt's evidence/state/trace is stored (the trace of a
        failed attempt belongs in `detail`); unsettled calls -> outcome_unknown; lease released. Counter unchanged."""
        now = self._clock()
        if detail is not None:
            _check_safe(_canonical(detail), "failure detail")
        with self._tx() as c:
            self._require_lease(c, inspection_id, lease_token)
            row = c.execute("SELECT attempts, failures_json FROM submissions WHERE inspection_id = ? "
                            "AND idempotency_key = ? AND lease_token = ? AND status = 'processing'",
                            (inspection_id, idempotency_key, lease_token)).fetchone()
            if row is None:
                raise StoreError(f"no processing submission {idempotency_key!r} under this lease")
            calls = self._unknown_calls(c, inspection_id, lease_token, now)
            f = self._loads(row[1], "failure audit") + [
                {"attempt": row[0], "status": "failed", "at": now, "error": error,
                 "unknown_outcome_calls": calls, "detail": detail}]
            c.execute("UPDATE submissions SET status = 'failed', failures_json = ?, updated_at = ? "
                      "WHERE inspection_id = ? AND idempotency_key = ?",
                      (_canonical(f), now, inspection_id, idempotency_key))
            c.execute("UPDATE inspections SET lease_token = NULL, lease_acquired_at = NULL, "
                      "lease_heartbeat_at = NULL WHERE id = ?", (inspection_id,))

    # ------------------------------------------------------------------ model-call accounting

    def reserve_model_call(self, inspection_id: str, lease_token: str, name: str, *, image_id: str | None = None,
                           idempotency_key: str | None = None, global_limit: int | None = None) -> int:
        """Record a model call BEFORE it is sent. Returns its ordinal (= the counter after this call).

        Stage 3 hook: MetaClient._reserve_call must call this (and abort the call if it raises) so that every call
        that may reach the API is counted exactly once, durably, before any network I/O. `global_limit` caps the
        calls reserved across ALL inspections in this database (a spending cap); checked in the same transaction.
        """
        now = self._clock()
        with self._tx() as c:
            rec = self._require_lease(c, inspection_id, lease_token)
            if rec.model_calls_reserved >= rec.model_call_limit:
                raise ModelCallBudgetExhausted(
                    f"inspection {inspection_id}: model call budget ({rec.model_call_limit}) exhausted")
            if global_limit is not None and self._total_calls(c) >= global_limit:
                raise ModelCallBudgetExhausted(f"global model call cap ({global_limit}) reached")
            attempt = None
            if idempotency_key is not None:
                row = c.execute("SELECT attempts FROM submissions WHERE inspection_id = ? AND idempotency_key = ? "
                                "AND lease_token = ? AND status = 'processing'",
                                (inspection_id, idempotency_key, lease_token)).fetchone()
                if row is None:
                    raise StoreError(f"no processing submission {idempotency_key!r} under this lease")
                attempt = row[0]
            ordinal = rec.model_calls_reserved + 1
            c.execute("UPDATE inspections SET model_calls_reserved = ?, lease_heartbeat_at = ? WHERE id = ?",
                      (ordinal, now, inspection_id))
            c.execute("INSERT INTO model_calls (inspection_id, ordinal, lease_token, idempotency_key, attempt, name, "
                      "image_id, status, reserved_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'reserved', ?)",
                      (inspection_id, ordinal, lease_token, idempotency_key, attempt, name, image_id, now))
        return ordinal

    @staticmethod
    def _total_calls(c: sqlite3.Connection) -> int:
        return int(c.execute("SELECT COALESCE(SUM(model_calls_reserved), 0) FROM inspections").fetchone()[0])

    def total_model_calls(self) -> int:
        """Model calls reserved across every inspection in this database (retries and unknown outcomes included)."""
        with self._tx(write=False) as c:
            return self._total_calls(c)

    def settle_model_call(self, inspection_id: str, lease_token: str, ordinal: int,
                          status: Literal["ok", "error"], detail: dict[str, Any] | None = None) -> None:
        """Record a reserved call's known outcome. Does not change the counter (a call that errored still counts:
        it was sent and may be billed)."""
        if detail is not None:
            _check_safe(_canonical(detail), "model call detail")
        with self._tx() as c:
            self._require_lease(c, inspection_id, lease_token)
            n = c.execute("UPDATE model_calls SET status = ?, settled_at = ?, detail_json = ? "
                          "WHERE inspection_id = ? AND ordinal = ? AND lease_token = ? AND status = 'reserved'",
                          (status, self._clock(), _canonical(detail) if detail is not None else None,
                           inspection_id, ordinal, lease_token)).rowcount
            if n != 1:
                raise StoreError(f"model call {ordinal} is not a reserved call under this lease")

    def list_model_calls(self, inspection_id: str) -> list[ModelCallRecord]:
        with self._tx(write=False) as c:
            rows = c.execute("SELECT ordinal, name, image_id, idempotency_key, attempt, status, reserved_at, "
                             "settled_at, detail_json FROM model_calls WHERE inspection_id = ? ORDER BY ordinal",
                             (inspection_id,)).fetchall()
        return [ModelCallRecord(o, n, i, k, a, s, r, t, self._loads(d, "model call detail"))
                for o, n, i, k, a, s, r, t, d in rows]

    # ------------------------------------------------------------------ the atomic step

    def commit_step(self, inspection_id: str, lease_token: str, expected_version: int, state: AgentState,
                    trace_events: list[TraceEvent], images: Mapping[str, NormalizedImage],
                    overlays: Mapping[str, bytes] | None = None, *, idempotency_key: str | None = None,
                    response: dict[str, Any] | None = None, release: bool = True) -> int:
        """Persist one agent step atomically; returns the new version.

        `state` is agent.snapshot() after the step, `trace_events` the full trace, `images` agent.images (only photos
        of new observations are inserted), `overlays` image_id -> JPEG for this step's photos. Stored observations,
        requests, history and trace must be an unchanged prefix of the new ones (append-only). With an idempotency
        key, the submission becomes 'done' with `response`. All or nothing.
        """
        overlays = overlays or {}
        if idempotency_key is not None and response is None:
            raise StoreError("a completed submission needs its response")
        if [e.seq for e in trace_events] != list(range(len(trace_events))) \
                or len(trace_events) != state.trace_event_count:
            raise StoreError("trace events must be the agent's full contiguous trace (0..trace_event_count-1)")
        obs_json = [o.model_dump_json() for o in state.observations]
        req_json = [r.model_dump_json() for r in state.requests]
        hist_json = [_canonical(h) for h in state.history]
        trace_json = [e.model_dump_json() for e in trace_events]
        for t in trace_json:
            _check_safe(t, "trace event")
        if response is not None:
            _check_safe(_canonical(response), "submission response")
        control = _Control(require_grounding=state.require_grounding, plan_with_muse=state.plan_with_muse,
                           budget=state.budget, gap_attempts=state.gap_attempts, exhausted=state.exhausted,
                           assessments=state.assessments, stop_reason=state.stop_reason,
                           declarations=state.declarations)
        assessments_json = _canonical([a.model_dump(mode="json") for a in state.assessments])
        now = self._clock()
        try:
            with self._tx() as c:
                rec = self._require_lease(c, inspection_id, lease_token)
                if rec.version != expected_version:
                    raise VersionConflict(f"inspection {inspection_id} is at version {rec.version}, "
                                          f"not {expected_version}")
                spec_json, control_json = c.execute("SELECT spec_json, control_json FROM inspections WHERE id = ?",
                                                    (inspection_id,)).fetchone()
                if InspectionSpec.model_validate_json(spec_json) != state.spec:
                    raise AppendOnlyViolation("snapshot belongs to a different specification")
                if self._loads(control_json, "control state").get("budget") != state.budget \
                        or rec.model_call_limit != state.model_call_limit:
                    raise AppendOnlyViolation("snapshot budget differs from the inspection's stored budget")
                stored_decl = [OperatorDeclaration.model_validate(d) for d in
                               self._loads(control_json, "control state").get("declarations") or []]
                if state.declarations[:len(stored_decl)] != stored_decl:
                    raise AppendOnlyViolation("operator declarations are append-only")

                n_obs = self._append_prefix(c, "observations", "seq", "record_json", inspection_id, obs_json)
                n_req = self._append_prefix(c, "next_view_requests", "ordinal", "request_json", inspection_id,
                                            req_json)
                n_hist = self._append_prefix(c, "steps", "step_no", "history_json", inspection_id, hist_json)
                n_tr = self._append_prefix(c, "trace_events", "seq", "event_json", inspection_id, trace_json)

                for o in state.observations[n_obs:]:
                    if c.execute("SELECT 1 FROM photos WHERE inspection_id = ? AND image_id = ?",
                                 (inspection_id, o.image_id)).fetchone():
                        continue
                    img = images.get(o.image_id)
                    if img is None:
                        raise StoreError(f"observation {o.seq} has no photo {o.image_id} to store")
                    c.execute("INSERT INTO photos (inspection_id, image_id, source_name, width, height, orig_width, "
                              "orig_height, jpeg, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (inspection_id, img.image_id, img.source_name, img.width, img.height,
                               img.original_size[0], img.original_size[1], img.jpeg_bytes, now))
                for image_id, jpeg in overlays.items():
                    if not jpeg or c.execute("UPDATE photos SET overlay_jpeg = ? WHERE inspection_id = ? "
                                             "AND image_id = ?", (jpeg, inspection_id, image_id)).rowcount != 1:
                        raise StoreError(f"overlay for unknown photo {image_id} (or empty overlay)")
                for o, j in zip(state.observations[n_obs:], obs_json[n_obs:]):
                    c.execute("INSERT INTO observations (inspection_id, seq, image_id, epoch, responding_to, "
                              "record_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (inspection_id, o.seq, o.image_id, o.epoch, o.responding_to, j, now))
                for i, (r, j) in enumerate(zip(state.requests[n_req:], req_json[n_req:]), start=n_req + 1):
                    c.execute("INSERT INTO next_view_requests (inspection_id, ordinal, request_id, after_image_id, "
                              "gap_key, request_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (inspection_id, i, r.id, r.after_image_id, r.gap_key, j, now))
                for i, (h, j) in enumerate(zip(state.history[n_hist:], hist_json[n_hist:]), start=n_hist + 1):
                    c.execute("INSERT INTO steps (inspection_id, step_no, kind, history_json, assessments_json, "
                              "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                              (inspection_id, i, _step_kind(h), j, assessments_json, now))
                self._insert_trace(c, inspection_id, trace_events[n_tr:], trace_json[n_tr:])

                # Unsettled reservations of this attempt: outcome not recorded (counter untouched).
                self._unknown_calls(c, inspection_id, lease_token, now)
                counter = max(rec.model_calls_reserved, state.model_calls_started)
                lease_sql = ("lease_token = NULL, lease_acquired_at = NULL, lease_heartbeat_at = NULL"
                             if release else "lease_heartbeat_at = :now")
                c.execute(f"UPDATE inspections SET control_json = :control, status = :status, "
                          f"stop_reason = :stop, epoch = :epoch, model_calls_reserved = :calls, version = :v, "
                          f"updated_at = :now, {lease_sql} WHERE id = :id",
                          {"control": control.model_dump_json(), "status": "stopped" if state.stop_reason else "open",
                           "stop": state.stop_reason, "epoch": state.epoch, "calls": counter,
                           "v": rec.version + 1, "now": now, "id": inspection_id})
                if idempotency_key is not None:
                    n = c.execute("UPDATE submissions SET status = 'done', response_json = ?, updated_at = ? "
                                  "WHERE inspection_id = ? AND idempotency_key = ? AND lease_token = ? "
                                  "AND status = 'processing'",
                                  (_canonical(response), now, inspection_id, idempotency_key, lease_token)).rowcount
                    if n != 1:
                        raise StoreError(f"no processing submission {idempotency_key!r} under this lease")
                return rec.version + 1
        except sqlite3.IntegrityError as e:
            raise StoreError(f"step rejected by database constraints (nothing stored): {e}") from e

    @staticmethod
    def _append_prefix(c: sqlite3.Connection, table: str, order_col: str, json_col: str, inspection_id: str,
                       new: list[str]) -> int:
        stored = [r[0] for r in c.execute(
            f"SELECT {json_col} FROM {table} WHERE inspection_id = ? ORDER BY {order_col}", (inspection_id,))]
        if len(stored) > len(new) or any(a != b for a, b in zip(stored, new)):
            raise AppendOnlyViolation(f"{table}: the new state does not extend the stored records unchanged")
        return len(stored)

    @staticmethod
    def _insert_trace(c: sqlite3.Connection, inspection_id: str, events: list[TraceEvent], texts: list[str]) -> None:
        for e, j in zip(events, texts):
            c.execute("INSERT INTO trace_events (inspection_id, seq, kind, name, source, event_json) "
                      "VALUES (?, ?, ?, ?, ?, ?)", (inspection_id, e.seq, e.kind, e.name, e.source, j))
