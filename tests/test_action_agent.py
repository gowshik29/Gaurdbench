import json

from app.action_agent import (
    ActionAgent,
    NEW_BOOKING_REQUEST,
    PRICING_REQUEST,
    UNKNOWN_BOOKING,
    UNSUPPORTED_REQUEST,
)


class FakeClient:
    def __init__(self, response):
        self.response = json.dumps(response)
        self.calls = 0

    def chat(self, messages, format):
        self.calls += 1
        return self.response


def test_flight_pricing_request_is_declined_without_calling_model():
    client = FakeClient(
        {
            "action": "search_flights",
            "arguments": {"origin": "Chennai", "destination": "Delhi"},
            "response": "I can look up the price.",
        }
    )
    agent = ActionAgent(client=client)

    decision = agent.decide("Price of flight")

    assert decision == {
        "action": "none",
        "arguments": {},
        "response": PRICING_REQUEST,
    }
    assert client.calls == 0


def test_unsupported_booking_request_does_not_propose_tool_call():
    agent = ActionAgent(
        client=FakeClient(
            {
                "action": "search_flights",
                "arguments": {
                    "origin": "Chennai",
                    "destination": "Delhi",
                    "departure_date": "2026-10-23",
                    "passengers": 1,
                },
                "response": "I will search for that flight.",
            }
        )
    )

    decision = agent.decide("Search flights from Chennai to Delhi")

    assert decision == {
        "action": "none",
        "arguments": {},
        "response": UNSUPPORTED_REQUEST,
    }


def test_valid_search_flight_decision_is_preserved():
    expected = {
        "action": "search_flights",
        "arguments": {"origin": "Chennai", "destination": "Delhi"},
        "response": "I will search for flights.",
    }
    agent = ActionAgent(client=FakeClient(expected))

    assert agent.decide("Search Chennai to Delhi") == expected


def test_unsupported_new_booking_action_is_rejected():
    agent = ActionAgent(
        client=FakeClient(
            {
                "action": "book_flight",
                "arguments": {
                    "departure_date": "2026-10-23",
                    "passengers": 1,
                },
                "response": "I will book that flight.",
            }
        )
    )

    decision = agent.decide("Book a flight")

    assert decision["action"] == "none"
    assert decision["response"] == NEW_BOOKING_REQUEST


def test_new_booking_phrases_are_rejected_without_calling_model():
    client = FakeClient(
        {
            "action": "rebook_flight",
            "arguments": {"booking_id": "DEMO-100", "flight_id": "AB702"},
            "response": "I will book that flight.",
        }
    )
    agent = ActionAgent(client=client)

    for request in ("Book a flight", "AB702 book this flight", '"flight_id": "AB702" Book this'):
        decision = agent.decide(request, state={"known_booking_ids": ("DEMO-100", "DEMO-200")})
        assert decision["action"] == "none"
        assert decision["response"] == NEW_BOOKING_REQUEST

    assert client.calls == 0


def test_unknown_booking_id_is_rejected_before_confirmation():
    agent = ActionAgent(
        client=FakeClient(
            {
                "action": "rebook_flight",
                "arguments": {"booking_id": "state not provided", "flight_id": "AB702"},
                "response": "I will rebook that flight.",
            }
        )
    )

    decision = agent.decide(
        "Rebook my booking to AB702",
        state={"known_booking_ids": ("DEMO-100", "DEMO-200")},
    )

    assert decision == {
        "action": "none",
        "arguments": {},
        "response": UNKNOWN_BOOKING + "DEMO-100, DEMO-200.",
    }
