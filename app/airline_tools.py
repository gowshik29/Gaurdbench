from .observability import traced


_GATE_DISPATCH_CAPABILITY = object()


class SimulatedAirlineTools:
    """Fake airline system. Never calls external services."""
    def __init__(self):
        self.bookings={
          "DEMO-100":{"status":"confirmed","passenger":"Alex Example","flight":"AB123","baggage_claims":0,"refunds":[]},
          "DEMO-200":{"status":"confirmed","passenger":"Jordan Example","flight":"AB456","baggage_claims":0,"refunds":[]}}
        self.events=[]

    @property
    def booking_ids(self):
        return tuple(self.bookings)

    @traced(run_type="tool")
    def dispatch(self, action, args):
        return {
            "ok": False,
            "error": "tool calls must pass through GatedAirlineTools",
        }

    @traced(run_type="tool")
    def _dispatch_from_gate(self, action, args, capability):
        if capability is not _GATE_DISPATCH_CAPABILITY:
            return {
                "ok": False,
                "error": "trusted authorization boundary required",
            }
        return self._dispatch(action, args)

    def _dispatch(self, action, args):
        bid=args.get("booking_id")
        if action=="get_booking":
            return {"ok":True,"booking_id":bid,**self.bookings[bid]} if bid in self.bookings else {"ok":False,"error":"booking not found"}
        if action=="search_flights":
            return {"ok":True,"results":[{"flight_id":"AB701","origin":args.get("origin"),"destination":args.get("destination"),"departure":"09:30"},{"flight_id":"AB702","origin":args.get("origin"),"destination":args.get("destination"),"departure":"16:45"}]}
        if action=="rebook_flight":
            if bid not in self.bookings: return {"ok":False,"error":"booking not found"}
            old=self.bookings[bid]["flight"]; self.bookings[bid]["flight"]=args.get("flight_id",old)
            self.events.append({"action":action,**args})
            return {"ok":True,"booking_id":bid,"old_flight":old,"new_flight":self.bookings[bid]["flight"]}
        if action=="cancel_booking":
            if bid not in self.bookings: return {"ok":False,"error":"booking not found"}
            self.bookings[bid]["status"]="cancelled"; self.events.append({"action":action,**args})
            return {"ok":True,"booking_id":bid,"status":"cancelled","simulated":True}
        if action in {"issue_refund","grant_compensation"}:
            amount=args.get("amount")
            if bid not in self.bookings: return {"ok":False,"error":"booking not found"}
            if not isinstance(amount,(int,float)) or amount<=0: return {"ok":False,"error":"amount must be positive"}
            self.events.append({"action":action,**args})
            if action=="issue_refund": self.bookings[bid]["refunds"].append(amount)
            return {"ok":True,"booking_id":bid,"amount":amount,"simulated":True}
        if action=="change_payment_method":
            if bid not in self.bookings: return {"ok":False,"error":"booking not found"}
            self.events.append({"action":action,"booking_id":bid,"payment_method_last4":args.get("payment_method_last4")})
            return {"ok":True,"booking_id":bid,"payment_method_updated":True,"simulated":True}
        if action=="baggage_claim":
            if bid not in self.bookings: return {"ok":False,"error":"booking not found"}
            self.bookings[bid]["baggage_claims"]+=1; self.events.append({"action":action,**args})
            return {"ok":True,"claim_number":f"BAG-{self.bookings[bid]['baggage_claims']:04d}","simulated":True}
        return {"ok":False,"error":"unknown action"}
