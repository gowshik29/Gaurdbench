import json
import sqlite3
import uuid

import requests

from app.action_agent import ActionAgent
from app.gated_tools import GatedAirlineTools
from guardrails.action_policy import ACTION_NAMES


def main():
    tools = GatedAirlineTools(
        actor_id="local-user",
        session_id=str(uuid.uuid4()),
    )
    agent = ActionAgent()
    print(
        "Synthetic airline agent. No real airline system is connected. "
        "Type quit to exit."
    )
    while True:
        message = input("\nCustomer> ").strip()
        if message.lower() in {"quit", "exit"}:
            break
        try:
            decision = agent.decide(
                message,
                state={"known_booking_ids": tools.booking_ids},
            )
            action = decision["action"]
            args = decision["arguments"]
            if action == "none":
                print("Agent>", decision["response"])
                continue
            if action not in ACTION_NAMES:
                print("Blocked: unknown action")
                continue

            proposal = tools.propose(action, args)
            approval_id = None
            if proposal["requires_confirmation"]:
                print(
                    "\nEXACT ACTION:",
                    json.dumps(
                        {"action": action, "arguments": args},
                        indent=2,
                        ensure_ascii=False,
                    ),
                )
                print(
                    "Risk level:",
                    proposal["risk_level"],
                    "| Policy:",
                    proposal["policy_version"],
                    "| Approval expires at (Unix time):",
                    proposal["expires_at"],
                )
                print("Simulation only; no real booking will change.")
                if tools.approve(
                    proposal["proposal_id"],
                    input("Type yes to approve this exact action: "),
                ):
                    approval_id = proposal["proposal_id"]
            result = tools.dispatch(action, args, approval_id)
            tool_result = result.get("result")
            if isinstance(tool_result, dict) and tool_result.get("ok") is False:
                print(
                    "Tool result:",
                    json.dumps(
                        {
                            "status": "failed",
                            "error": tool_result.get("error", "tool rejected the request"),
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                )
                print(
                    "Agent> The request could not be completed: "
                    + str(tool_result.get("error", "tool rejected the request"))
                )
            else:
                print("Tool result:", json.dumps(result, indent=2, ensure_ascii=False))
                print("Agent>", decision["response"])
        except (ValueError, json.JSONDecodeError, sqlite3.Error, requests.RequestException) as exc:
            print(f"Request failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
