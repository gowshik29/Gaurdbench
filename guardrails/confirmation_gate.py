import hashlib
import argparse
import json
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from app.observability import traced
from app.settings import get_settings
from .action_policy import ACTION_NAMES, ActionPolicy, DEFAULT_POLICY


def _json_safe(value):
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def canonical_json(value):
    return json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def fingerprint(action, args):
    payload = canonical_json({"action": action, "arguments": args})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_action(action, args):
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    if any(not isinstance(key, str) for key in args):
        return "argument names must be strings"
    try:
        serialized = canonical_json(args)
    except (TypeError, ValueError):
        return "arguments must contain only finite JSON values"
    if len(serialized.encode("utf-8")) > 16_384:
        return "arguments exceed the 16 KiB limit"

    allowed = {
        "get_booking": {"booking_id"},
        "search_flights": {"origin", "destination"},
        "rebook_flight": {"booking_id", "flight_id"},
        "cancel_booking": {"booking_id", "reason"},
        "issue_refund": {"booking_id", "amount", "reason"},
        "grant_compensation": {"booking_id", "amount", "reason"},
        "change_payment_method": {"booking_id", "payment_method_last4"},
        "baggage_claim": {"booking_id", "description"},
    }[action]
    unknown = set(args) - allowed
    if unknown:
        return "unsupported argument(s): " + ", ".join(sorted(unknown))

    required = {
        "get_booking": ("booking_id",),
        "search_flights": ("origin", "destination"),
        "rebook_flight": ("booking_id", "flight_id"),
        "cancel_booking": ("booking_id",),
        "issue_refund": ("booking_id", "amount"),
        "grant_compensation": ("booking_id", "amount"),
        "change_payment_method": ("booking_id", "payment_method_last4"),
        "baggage_claim": ("booking_id",),
    }[action]
    for name in required:
        value = args.get(name)
        if not isinstance(value, str) or not value.strip():
            if name in {"amount"}:
                continue
            return f"{name} must be a non-empty string"

    if action in {"issue_refund", "grant_compensation"}:
        amount = args.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return "amount must be a positive finite number"
        if not math.isfinite(amount) or amount <= 0:
            return "amount must be a positive finite number"
    if action == "change_payment_method":
        last4 = args["payment_method_last4"]
        if len(last4) != 4 or not last4.isdigit():
            return "payment_method_last4 must contain exactly four digits"
    return None


class ConfirmationGate:
    """Fail-closed boundary with contextual, expiring, one-use approvals."""

    def __init__(
        self,
        db_path=None,
        policy=None,
        approval_ttl_seconds=300,
        clock=time.time,
    ):
        if (
            isinstance(approval_ttl_seconds, bool)
            or not isinstance(approval_ttl_seconds, (int, float))
            or not math.isfinite(approval_ttl_seconds)
            or approval_ttl_seconds <= 0
        ):
            raise ValueError("approval_ttl_seconds must be a positive finite number")
        self.db_path = Path(db_path or get_settings()["audit_db"])
        self.policy = policy or DEFAULT_POLICY
        if not isinstance(self.policy, ActionPolicy):
            raise ValueError("policy must be an ActionPolicy")
        self.approval_ttl_seconds = float(approval_ttl_seconds)
        self._clock = clock
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self):
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS audit_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    proposal_id TEXT,
                    details_json TEXT NOT NULL,
                    event_id TEXT,
                    actor_id TEXT NOT NULL DEFAULT 'local',
                    session_id TEXT NOT NULL DEFAULT 'local',
                    policy_version TEXT NOT NULL DEFAULT 'legacy',
                    outcome TEXT NOT NULL DEFAULT 'recorded',
                    reason TEXT,
                    previous_hash TEXT,
                    event_hash TEXT
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS proposals(
                    proposal_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    approved_at REAL,
                    actor_id TEXT NOT NULL DEFAULT 'local',
                    session_id TEXT NOT NULL DEFAULT 'local',
                    policy_version TEXT NOT NULL DEFAULT 'legacy',
                    expires_at REAL
                )"""
            )
            self._add_columns(
                connection,
                "audit_events",
                {
                    "event_id": "TEXT",
                    "actor_id": "TEXT NOT NULL DEFAULT 'local'",
                    "session_id": "TEXT NOT NULL DEFAULT 'local'",
                    "policy_version": "TEXT NOT NULL DEFAULT 'legacy'",
                    "outcome": "TEXT NOT NULL DEFAULT 'recorded'",
                    "reason": "TEXT",
                    "previous_hash": "TEXT",
                    "event_hash": "TEXT",
                },
            )
            self._add_columns(
                connection,
                "proposals",
                {
                    "actor_id": "TEXT NOT NULL DEFAULT 'local'",
                    "session_id": "TEXT NOT NULL DEFAULT 'local'",
                    "policy_version": "TEXT NOT NULL DEFAULT 'legacy'",
                    "expires_at": "REAL",
                },
            )
            self._backfill_event_chain(connection)
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_events_event_id "
                "ON audit_events(event_id)"
            )

    @staticmethod
    def _add_columns(connection, table, columns):
        existing = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        for name, declaration in columns.items():
            if name not in existing:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"
                )

    @staticmethod
    def _event_digest(event):
        return hashlib.sha256(canonical_json(event).encode("utf-8")).hexdigest()

    @classmethod
    def _backfill_event_chain(cls, connection):
        rows = connection.execute(
            """SELECT id,ts,event_type,action,args_json,fingerprint,proposal_id,
            details_json,event_id,actor_id,session_id,policy_version,outcome,reason,
            previous_hash,event_hash FROM audit_events ORDER BY id"""
        ).fetchall()
        previous_hash = ""
        for row in rows:
            if row[8] and row[14] is not None and row[15] is not None:
                previous_hash = row[15]
                continue
            event_id = row[8] or str(uuid.uuid4())
            event = {
                "event_id": event_id,
                "timestamp": row[1],
                "event_type": row[2],
                "action": row[3],
                "arguments_json": row[4],
                "fingerprint": row[5],
                "proposal_id": row[6],
                "details_json": row[7],
                "actor_id": row[9] or "local",
                "session_id": row[10] or "local",
                "policy_version": row[11] or "legacy",
                "outcome": row[12] or "recorded",
                "reason": row[13],
                "previous_hash": previous_hash,
            }
            event_hash = cls._event_digest(event)
            connection.execute(
                """UPDATE audit_events SET event_id=?,actor_id=?,session_id=?,
                policy_version=?,outcome=?,reason=?,previous_hash=?,event_hash=?
                WHERE id=?""",
                (
                    event_id,
                    event["actor_id"],
                    event["session_id"],
                    event["policy_version"],
                    event["outcome"],
                    event["reason"],
                    previous_hash,
                    event_hash,
                    row[0],
                ),
            )
            previous_hash = event_hash

    def _insert_event(
        self,
        connection,
        kind,
        action,
        args,
        fp,
        proposal_id=None,
        details=None,
        actor_id="local",
        session_id="local",
        outcome="recorded",
        reason=None,
    ):
        event_id = str(uuid.uuid4())
        timestamp = self._clock()
        previous_hash = connection.execute(
            "SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous_hash[0] if previous_hash else ""
        args_json = canonical_json(args)
        details_json = canonical_json(details or {})
        event = {
            "event_id": event_id,
            "timestamp": timestamp,
            "event_type": kind,
            "action": action,
            "arguments_json": args_json,
            "fingerprint": fp,
            "proposal_id": proposal_id,
            "details_json": details_json,
            "actor_id": actor_id,
            "session_id": session_id,
            "policy_version": self.policy.version,
            "outcome": outcome,
            "reason": reason,
            "previous_hash": previous_hash,
        }
        event_hash = self._event_digest(event)
        connection.execute(
            """INSERT INTO audit_events(
                ts,event_type,action,args_json,fingerprint,proposal_id,details_json,
                event_id,actor_id,session_id,policy_version,outcome,reason,
                previous_hash,event_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                timestamp,
                kind,
                action,
                args_json,
                fp,
                proposal_id,
                details_json,
                event_id,
                actor_id,
                session_id,
                self.policy.version,
                outcome,
                reason,
                previous_hash,
                event_hash,
            ),
        )

    def _event(
        self,
        kind,
        action,
        args,
        fp,
        proposal_id=None,
        details=None,
        actor_id="local",
        session_id="local",
        outcome="recorded",
        reason=None,
    ):
        with self._connect() as connection:
            self._insert_event(
                connection,
                kind,
                action,
                args,
                fp,
                proposal_id,
                details,
                actor_id,
                session_id,
                outcome,
                reason,
            )

    @staticmethod
    def _validate_identity(actor_id, session_id):
        for name, value in (("actor_id", actor_id), ("session_id", session_id)):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 128
                or value != value.strip()
            ):
                raise ValueError(
                    f"{name} must be a non-empty, trimmed string of at most 128 characters"
                )

    def audit_events(self):
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT ts,event_type,action,args_json,fingerprint,proposal_id,
                details_json,event_id,actor_id,session_id,policy_version,outcome,
                reason,previous_hash,event_hash
                FROM audit_events ORDER BY id"""
            ).fetchall()
        return [
            {
                "timestamp": row[0],
                "event_type": row[1],
                "action": row[2],
                "arguments": json.loads(row[3]),
                "fingerprint": row[4],
                "proposal_id": row[5],
                "details": json.loads(row[6]),
                "event_id": row[7],
                "actor_id": row[8],
                "session_id": row[9],
                "policy_version": row[10],
                "outcome": row[11],
                "reason": row[12],
                "previous_hash": row[13],
                "event_hash": row[14],
            }
            for row in rows
        ]

    def verify_audit_chain(self):
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT ts,event_type,action,args_json,fingerprint,proposal_id,
                details_json,event_id,actor_id,session_id,policy_version,outcome,
                reason,previous_hash,event_hash FROM audit_events ORDER BY id"""
            ).fetchall()
        previous_hash = ""
        for index, row in enumerate(rows, start=1):
            event = {
                "event_id": row[7],
                "timestamp": row[0],
                "event_type": row[1],
                "action": row[2],
                "arguments_json": row[3],
                "fingerprint": row[4],
                "proposal_id": row[5],
                "details_json": row[6],
                "actor_id": row[8],
                "session_id": row[9],
                "policy_version": row[10],
                "outcome": row[11],
                "reason": row[12],
                "previous_hash": row[13],
            }
            if row[13] != previous_hash or row[14] != self._event_digest(event):
                return {
                    "valid": False,
                    "events_checked": index - 1,
                    "invalid_event": index,
                }
            previous_hash = row[14]
        return {"valid": True, "events_checked": len(rows), "invalid_event": None}

    @staticmethod
    def _validate_external_action(action, args):
        if not isinstance(action, str) or not action.strip() or len(action) > 128:
            return "external action name must be a non-empty string of at most 128 characters"
        if not isinstance(args, dict) or any(not isinstance(key, str) for key in args):
            return "external action arguments must be a JSON object with string keys"
        try:
            serialized = canonical_json(args)
        except (TypeError, ValueError):
            return "external action arguments must contain only finite JSON values"
        if len(serialized.encode("utf-8")) > 16_384:
            return "external action arguments exceed the 16 KiB limit"
        return None

    @traced(run_type="tool")
    def execute_external_readonly(
        self,
        action,
        args,
        tool,
        actor_id="local",
        session_id="local",
    ):
        """Record and dispatch a read-only external call through the same boundary."""
        self._validate_identity(actor_id, session_id)
        validation_error = self._validate_external_action(action, args)
        if validation_error:
            return {"status": "blocked", "reason": validation_error}
        if not callable(tool):
            return {"status": "blocked", "reason": "tool is not callable"}
        action_fingerprint = fingerprint(action, args)
        self._event(
            "external_readonly_tool_dispatched",
            action,
            args,
            action_fingerprint,
            actor_id=actor_id,
            session_id=session_id,
            outcome="dispatched",
        )
        try:
            result = tool(args)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._event(
                "external_readonly_tool_failed",
                action,
                args,
                action_fingerprint,
                details={"error": error},
                actor_id=actor_id,
                session_id=session_id,
                outcome="failed",
                reason=error,
            )
            return {"status": "failed", "error": error}
        self._event(
            "external_readonly_tool_result",
            action,
            args,
            action_fingerprint,
            details={"result": result},
            actor_id=actor_id,
            session_id=session_id,
            outcome="executed",
        )
        return {"status": "executed", "result": result}

    @traced(run_type="tool")
    def propose(self, action, args, actor_id="local", session_id="local"):
        self._validate_identity(actor_id, session_id)
        if not isinstance(action, str) or action not in ACTION_NAMES:
            raise ValueError("Action not allow-listed: " + str(action))
        validation_error = validate_action(action, args)
        if validation_error:
            raise ValueError(validation_error)

        proposal_id = str(uuid.uuid4())
        action_fingerprint = fingerprint(action, args)
        created_at = self._clock()
        expires_at = created_at + self.approval_ttl_seconds
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO proposals(
                proposal_id,action,args_json,fingerprint,status,created_at,approved_at,
                actor_id,session_id,policy_version,expires_at
                ) VALUES(?,?,?,?,?,?,NULL,?,?,?,?)""",
                (
                    proposal_id,
                    action,
                    canonical_json(args),
                    action_fingerprint,
                    "pending",
                    created_at,
                    actor_id,
                    session_id,
                    self.policy.version,
                    expires_at,
                ),
            )
        self._event(
            "sensitive_action_proposed"
            if self.policy.requires_approval(action)
            else "action_proposed",
            action,
            args,
            action_fingerprint,
            proposal_id,
            actor_id=actor_id,
            session_id=session_id,
        )
        return {
            "proposal_id": proposal_id,
            "action": action,
            "arguments": args,
            "fingerprint": action_fingerprint,
            "requires_confirmation": self.policy.requires_approval(action),
            "risk_level": self.policy.rule_for(action).risk_level.value,
            "policy_version": self.policy.version,
            "expires_at": expires_at,
            "actor_id": actor_id,
            "session_id": session_id,
        }

    @traced(run_type="tool")
    def propose_external(self, action, args, actor_id="local", session_id="local"):
        self._validate_identity(actor_id, session_id)
        validation_error = self._validate_external_action(action, args)
        if validation_error:
            raise ValueError(validation_error)
        proposal_id = str(uuid.uuid4())
        action_fingerprint = fingerprint(action, args)
        created_at = self._clock()
        expires_at = created_at + self.approval_ttl_seconds
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO proposals(
                proposal_id,action,args_json,fingerprint,status,created_at,approved_at,
                actor_id,session_id,policy_version,expires_at
                ) VALUES(?,?,?,?,?,?,NULL,?,?,?,?)""",
                (
                    proposal_id,
                    action,
                    canonical_json(args),
                    action_fingerprint,
                    "pending",
                    created_at,
                    actor_id,
                    session_id,
                    self.policy.version,
                    expires_at,
                ),
            )
        self._event(
            "external_mutating_tool_proposed",
            action,
            args,
            action_fingerprint,
            proposal_id,
            actor_id=actor_id,
            session_id=session_id,
        )
        return {
            "proposal_id": proposal_id,
            "action": action,
            "arguments": args,
            "fingerprint": action_fingerprint,
            "requires_confirmation": True,
            "policy_version": self.policy.version,
            "expires_at": expires_at,
            "actor_id": actor_id,
            "session_id": session_id,
        }

    @traced(run_type="tool")
    def approve(
        self,
        proposal_id,
        answer,
        channel="local_cli",
        actor_id="local",
        session_id="local",
    ):
        self._validate_identity(actor_id, session_id)
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError("confirmation channel must be a non-empty string")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT action,args_json,fingerprint,status,actor_id,session_id,
                policy_version,expires_at FROM proposals WHERE proposal_id=?""",
                (proposal_id,),
            ).fetchone()
            if not row:
                self._insert_event(
                    connection,
                    "approval_rejected",
                    "unknown",
                    {},
                    fingerprint("unknown", {}),
                    proposal_id,
                    {"channel": channel},
                    actor_id=actor_id,
                    session_id=session_id,
                    outcome="blocked",
                    reason="missing or unknown proposal",
                )
                return False
            if row[3] != "pending":
                self._insert_event(
                    connection,
                    "approval_rejected",
                    row[0],
                    json.loads(row[1]),
                    row[2],
                    proposal_id,
                    {"channel": channel},
                    actor_id=actor_id,
                    session_id=session_id,
                    outcome="blocked",
                    reason="proposal is not pending",
                )
                return False
            if (
                row[4] != actor_id
                or row[5] != session_id
                or row[6] != self.policy.version
            ):
                reason = (
                    "approval actor or session does not match"
                    if row[4] != actor_id or row[5] != session_id
                    else "approval policy version does not match"
                )
                self._insert_event(
                    connection,
                    "approval_rejected",
                    row[0],
                    json.loads(row[1]),
                    row[2],
                    proposal_id,
                    {"channel": channel},
                    actor_id=actor_id,
                    session_id=session_id,
                    outcome="blocked",
                    reason=reason,
                )
                return False
            if row[7] is not None and self._clock() >= row[7]:
                connection.execute(
                    "UPDATE proposals SET status='expired' WHERE proposal_id=? AND status='pending'",
                    (proposal_id,),
                )
                self._insert_event(
                    connection,
                    "approval_expired",
                    row[0],
                    json.loads(row[1]),
                    row[2],
                    proposal_id,
                    {"reason": "proposal expired before approval"},
                    actor_id=actor_id,
                    session_id=session_id,
                    outcome="blocked",
                    reason="proposal expired before approval",
                )
                return False

            approved = isinstance(answer, str) and answer.strip().lower() == "yes"
            status = "approved" if approved else "denied"
            cursor = connection.execute(
                """UPDATE proposals SET status=?,approved_at=?
                WHERE proposal_id=? AND status='pending'""",
                (status, self._clock() if approved else None, proposal_id),
            )
            if cursor.rowcount != 1:
                return False
            self._insert_event(
                connection,
                "explicit_confirmation_received" if approved else "sensitive_action_denied",
                row[0],
                json.loads(row[1]),
                row[2],
                proposal_id,
                {"channel": channel, "confirmation": "yes"}
                if approved
                else {"channel": channel, "reason": "not explicit yes"},
                actor_id=actor_id,
                session_id=session_id,
                outcome="approved" if approved else "denied",
                reason=None if approved else "not explicit yes",
            )
        return approved

    @traced(run_type="tool")
    def execute_external(
        self,
        action,
        args,
        tool,
        approval_id=None,
        actor_id="local",
        session_id="local",
    ):
        self._validate_identity(actor_id, session_id)
        validation_error = self._validate_external_action(action, args)
        if validation_error:
            return {"status": "blocked", "reason": validation_error}
        if not callable(tool):
            return {"status": "blocked", "reason": "tool is not callable"}
        action_fingerprint = fingerprint(action, args)
        reason = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = (
                connection.execute(
                    """SELECT action,args_json,fingerprint,status,actor_id,session_id,
                    policy_version,expires_at FROM proposals WHERE proposal_id=?""",
                    (approval_id,),
                ).fetchone()
                if approval_id
                else None
            )
            if not row:
                reason = "missing or unknown approval"
            elif (
                row[0] != action
                or row[1] != canonical_json(args)
                or row[2] != action_fingerprint
            ):
                reason = "approved action or arguments do not match"
            elif row[3] != "approved":
                reason = "approval is denied, pending, or already consumed"
            elif row[4] != actor_id or row[5] != session_id:
                reason = "approval actor or session does not match"
            elif row[6] != self.policy.version:
                reason = "approval policy version does not match"
            elif row[7] is not None and self._clock() >= row[7]:
                reason = "approval has expired"
            else:
                cursor = connection.execute(
                    """UPDATE proposals SET status='consumed'
                    WHERE proposal_id=? AND status='approved'""",
                    (approval_id,),
                )
                if cursor.rowcount != 1:
                    reason = "approval is denied, pending, or already consumed"
                else:
                    self._insert_event(
                        connection,
                        "external_mutating_tool_executed",
                        action,
                        args,
                        action_fingerprint,
                        approval_id,
                        actor_id=actor_id,
                        session_id=session_id,
                        outcome="executed",
                    )
            if reason:
                self._insert_event(
                    connection,
                    "external_mutating_tool_blocked",
                    action,
                    args,
                    action_fingerprint,
                    approval_id,
                    {"reason": reason},
                    actor_id=actor_id,
                    session_id=session_id,
                    outcome="blocked",
                    reason=reason,
                )
        if reason:
            return {"status": "blocked", "reason": reason}

        try:
            result = tool(args)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._event(
                "action_failed",
                action,
                args,
                action_fingerprint,
                approval_id,
                {"error": error},
                actor_id=actor_id,
                session_id=session_id,
                outcome="failed",
                reason=error,
            )
            return {"status": "failed", "error": error}
        self._event(
            "action_result",
            action,
            args,
            action_fingerprint,
            approval_id,
            {"result": result},
            actor_id=actor_id,
            session_id=session_id,
            outcome="executed",
        )
        return {"status": "executed", "result": result}

    @traced(run_type="tool")
    def execute(
        self,
        action,
        args,
        tool,
        approval_id=None,
        actor_id="local",
        session_id="local",
    ):
        self._validate_identity(actor_id, session_id)
        if not isinstance(action, str) or action not in ACTION_NAMES:
            return {"status": "blocked", "reason": "action not allow-listed"}
        validation_error = validate_action(action, args)
        if validation_error:
            return {"status": "blocked", "reason": validation_error}
        if not callable(tool):
            return {"status": "blocked", "reason": "tool is not callable"}

        action_fingerprint = fingerprint(action, args)
        if self.policy.requires_approval(action):
            reason = None
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = (
                    connection.execute(
                        """SELECT action,args_json,fingerprint,status,actor_id,session_id,
                        policy_version,expires_at FROM proposals WHERE proposal_id=?""",
                        (approval_id,),
                    ).fetchone()
                    if approval_id
                    else None
                )
                if not row:
                    reason = "missing or unknown approval"
                elif (
                    row[0] != action
                    or row[1] != canonical_json(args)
                    or row[2] != action_fingerprint
                ):
                    reason = "approved action or arguments do not match"
                elif row[3] != "approved":
                    reason = "approval is denied, pending, or already consumed"
                elif row[4] != actor_id or row[5] != session_id:
                    reason = "approval actor or session does not match"
                elif row[6] != self.policy.version:
                    reason = "approval policy version does not match"
                elif row[7] is not None and self._clock() >= row[7]:
                    reason = "approval has expired"
                else:
                    cursor = connection.execute(
                        """UPDATE proposals SET status='consumed'
                        WHERE proposal_id=? AND status='approved'""",
                        (approval_id,),
                    )
                    if cursor.rowcount != 1:
                        reason = "approval is denied, pending, or already consumed"
                    else:
                        self._insert_event(
                            connection,
                            "sensitive_action_executed",
                            action,
                            args,
                            action_fingerprint,
                            approval_id,
                            actor_id=actor_id,
                            session_id=session_id,
                            outcome="executed",
                        )
                if reason:
                    self._insert_event(
                        connection,
                        "sensitive_action_blocked",
                        action,
                        args,
                        action_fingerprint,
                        approval_id,
                        {"reason": reason},
                        actor_id=actor_id,
                        session_id=session_id,
                        outcome="blocked",
                        reason=reason,
                    )
            if reason:
                return {"status": "blocked", "reason": reason}
        else:
            self._event(
                "action_executed",
                action,
                args,
                action_fingerprint,
                actor_id=actor_id,
                session_id=session_id,
                outcome="executed",
            )

        try:
            result = tool(args)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._event(
                "action_failed",
                action,
                args,
                action_fingerprint,
                approval_id,
                {"error": error},
                actor_id=actor_id,
                session_id=session_id,
                outcome="failed",
                reason=error,
            )
            return {"status": "failed", "error": error}

        self._event(
            "action_result",
            action,
            args,
            action_fingerprint,
            approval_id,
            {"result": result},
            actor_id=actor_id,
            session_id=session_id,
            outcome="executed",
        )
        return {"status": "executed", "result": result}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify the GuardBench SQLite audit hash chain."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(get_settings()["audit_db"]),
        help="Audit database path.",
    )
    args = parser.parse_args(argv)
    result = ConfirmationGate(args.db).verify_audit_chain()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
