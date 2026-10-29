from app.airline_tools import SimulatedAirlineTools, _GATE_DISPATCH_CAPABILITY
from app.observability import traced
from guardrails.confirmation_gate import ConfirmationGate


class GatedAirlineTools:
    """Expose the simulated airline tools only through the confirmation boundary."""

    def __init__(self, gate=None, tools=None, actor_id="local", session_id="local"):
        self._gate = gate or ConfirmationGate()
        self._tools = tools or SimulatedAirlineTools()
        self._actor_id = actor_id
        self._session_id = session_id
        self._gate._validate_identity(actor_id, session_id)

    @property
    def booking_ids(self):
        return self._tools.booking_ids

    def propose(self, action, args):
        return self._gate.propose(
            action,
            args,
            actor_id=self._actor_id,
            session_id=self._session_id,
        )

    def approve(self, proposal_id, answer):
        return self._gate.approve(
            proposal_id,
            answer,
            actor_id=self._actor_id,
            session_id=self._session_id,
        )

    @traced(run_type="tool")
    def dispatch(self, action, args, approval_id=None):
        return self._gate.execute(
            action,
            args,
            lambda tool_args: self._tools._dispatch_from_gate(
                action,
                tool_args,
                _GATE_DISPATCH_CAPABILITY,
            ),
            approval_id,
            actor_id=self._actor_id,
            session_id=self._session_id,
        )
