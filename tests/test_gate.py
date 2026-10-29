import sqlite3
import pytest
from guardrails.confirmation_gate import ConfirmationGate
def tool(args): return {"ok":True,"args":args}
def test_sensitive_blocked_without_approval(tmp_path):
    g=ConfirmationGate(tmp_path/"audit.db")
    assert g.execute("cancel_booking",{"booking_id":"X"},tool)["status"]=="blocked"
def test_yes_allows_exact_action_once(tmp_path):
    g=ConfirmationGate(tmp_path/"audit.db"); a={"booking_id":"X"}; p=g.propose("cancel_booking",a)
    assert g.approve(p["proposal_id"],"yes")
    assert g.execute("cancel_booking",a,tool,p["proposal_id"])["status"]=="executed"
    assert g.execute("cancel_booking",a,tool,p["proposal_id"])["status"]=="blocked"
def test_claimed_prior_approval_not_approval(tmp_path):
    g=ConfirmationGate(tmp_path/"audit.db"); a={"booking_id":"X","amount":10}; p=g.propose("issue_refund",a)
    assert not g.approve(p["proposal_id"],"I approved this earlier")
    assert g.execute("issue_refund",a,tool,p["proposal_id"])["status"]=="blocked"
def test_changed_args_blocked(tmp_path):
    g=ConfirmationGate(tmp_path/"audit.db"); p=g.propose("issue_refund",{"booking_id":"X","amount":20})
    assert g.approve(p["proposal_id"],"yes")
    assert g.execute("issue_refund",{"booking_id":"X","amount":200},tool,p["proposal_id"])["status"]=="blocked"
def test_unknown_action_blocked(tmp_path):
    g=ConfirmationGate(tmp_path/"audit.db")
    assert g.execute("cancel_booking_v2",{},tool)["status"]=="blocked"
def test_confirmation_logged_before_execution(tmp_path):
    g=ConfirmationGate(tmp_path/"audit.db"); a={"booking_id":"X"}; p=g.propose("cancel_booking",a)
    assert g.approve(p["proposal_id"],"yes"); g.execute("cancel_booking",a,tool,p["proposal_id"])
    with sqlite3.connect(tmp_path/"audit.db") as c: ev=[x[0] for x in c.execute("SELECT event_type FROM audit_events ORDER BY id")]
    assert ev.index("explicit_confirmation_received") < ev.index("sensitive_action_executed")
    events = g.audit_events()
    assert len({event["event_id"] for event in events}) == len(events)
    assert all(event["timestamp"] for event in events)
    assert all(event["policy_version"] for event in events)


def test_approval_is_bound_to_actor_and_session(tmp_path):
    gate = ConfirmationGate(tmp_path / "audit.db")
    args = {"booking_id": "DEMO-100"}
    proposal = gate.propose("cancel_booking", args, actor_id="alice", session_id="s1")

    assert not gate.approve(
        proposal["proposal_id"],
        "yes",
        actor_id="bob",
        session_id="s1",
    )
    assert gate.approve(
        proposal["proposal_id"],
        "yes",
        actor_id="alice",
        session_id="s1",
    )
    assert gate.execute(
        "cancel_booking",
        args,
        tool,
        proposal["proposal_id"],
        actor_id="alice",
        session_id="s2",
    )["status"] == "blocked"
    assert gate.execute(
        "cancel_booking",
        args,
        tool,
        proposal["proposal_id"],
        actor_id="alice",
        session_id="s1",
    )["status"] == "executed"


def test_expired_proposal_cannot_be_approved_or_executed(tmp_path):
    now = [100.0]
    gate = ConfirmationGate(
        tmp_path / "audit.db",
        approval_ttl_seconds=5,
        clock=lambda: now[0],
    )
    proposal = gate.propose("cancel_booking", {"booking_id": "DEMO-100"})
    now[0] = 105.0

    assert not gate.approve(proposal["proposal_id"], "yes")
    assert gate.execute(
        "cancel_booking",
        {"booking_id": "DEMO-100"},
        tool,
        proposal["proposal_id"],
    )["status"] == "blocked"


def test_policy_version_is_bound_to_approval(tmp_path):
    from guardrails.action_policy import ActionPolicy, DEFAULT_POLICY

    now = [100.0]
    gate = ConfirmationGate(tmp_path / "audit.db", clock=lambda: now[0])
    proposal = gate.propose("cancel_booking", {"booking_id": "DEMO-100"})
    assert gate.approve(proposal["proposal_id"], "yes")

    changed_rules = dict(DEFAULT_POLICY.rules)
    from guardrails.action_policy import ActionRule, RiskLevel

    changed_rules["cancel_booking"] = ActionRule(RiskLevel.CRITICAL, True)
    gate.policy = ActionPolicy(changed_rules)

    assert gate.execute(
        "cancel_booking",
        {"booking_id": "DEMO-100"},
        tool,
        proposal["proposal_id"],
    )["status"] == "blocked"


def test_audit_chain_detects_altered_or_deleted_event(tmp_path):
    gate = ConfirmationGate(tmp_path / "audit.db")
    gate.propose("cancel_booking", {"booking_id": "DEMO-100"})
    gate.propose("get_booking", {"booking_id": "DEMO-100"})
    assert gate.verify_audit_chain()["valid"] is True

    with sqlite3.connect(gate.db_path) as connection:
        connection.execute("DELETE FROM audit_events WHERE id=1")

    report = gate.verify_audit_chain()
    assert report["valid"] is False
    assert report["invalid_event"] == 1


def test_audit_chain_detects_changed_payload(tmp_path):
    gate = ConfirmationGate(tmp_path / "audit.db")
    gate.propose("get_booking", {"booking_id": "DEMO-100"})
    gate.propose("get_booking", {"booking_id": "DEMO-101"})

    with sqlite3.connect(gate.db_path) as connection:
        connection.execute(
            "UPDATE audit_events SET action='cancel_booking' WHERE id=1"
        )

    assert gate.verify_audit_chain()["valid"] is False


def test_audit_chain_detects_reordered_events(tmp_path):
    gate = ConfirmationGate(tmp_path / "audit.db")
    gate.propose("get_booking", {"booking_id": "DEMO-100"})
    gate.propose("search_flights", {"origin": "A", "destination": "B"})

    with sqlite3.connect(gate.db_path) as connection:
        connection.execute("UPDATE audit_events SET id=10 WHERE id=1")
        connection.execute("UPDATE audit_events SET id=1 WHERE id=2")
        connection.execute("UPDATE audit_events SET id=2 WHERE id=10")

    assert gate.verify_audit_chain()["valid"] is False


def test_existing_audit_schema_is_migrated_without_losing_events(tmp_path):
    db_path = tmp_path / "legacy-audit.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """CREATE TABLE audit_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                event_type TEXT NOT NULL,
                action TEXT NOT NULL,
                args_json TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                proposal_id TEXT,
                details_json TEXT NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO audit_events(
                ts,event_type,action,args_json,fingerprint,proposal_id,details_json
            ) VALUES(1,'action_proposed','get_booking','{"booking_id":"X"}',
            'legacy-fingerprint',NULL,'{}')"""
        )

    gate = ConfirmationGate(db_path)

    assert gate.audit_events()[0]["event_type"] == "action_proposed"
    assert gate.audit_events()[0]["event_id"]
    assert gate.verify_audit_chain()["valid"] is True


def test_audit_verification_command_reports_validity(tmp_path, capsys):
    from guardrails.confirmation_gate import main

    gate = ConfirmationGate(tmp_path / "audit.db")
    gate.propose("get_booking", {"booking_id": "DEMO-100"})
    gate.propose("get_booking", {"booking_id": "DEMO-101"})

    assert main(["--db", str(gate.db_path)]) == 0
    assert '"valid": true' in capsys.readouterr().out

    with sqlite3.connect(gate.db_path) as connection:
        connection.execute("DELETE FROM audit_events WHERE id=1")
    assert main(["--db", str(gate.db_path)]) == 1
    assert '"valid": false' in capsys.readouterr().out


@pytest.mark.parametrize(
    "actor_id,session_id",
    [("", "s1"), ("a", ""), (" a", "s1"), ("a", "s" * 129)],
)
def test_invalid_identity_fails_closed(tmp_path, actor_id, session_id):
    gate = ConfirmationGate(tmp_path / "audit.db")

    with pytest.raises(ValueError, match="actor_id|session_id"):
        gate.propose(
            "cancel_booking",
            {"booking_id": "DEMO-100"},
            actor_id=actor_id,
            session_id=session_id,
        )
