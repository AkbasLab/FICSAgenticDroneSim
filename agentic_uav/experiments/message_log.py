"""The message log (AUV-07, 7.4): every message, what became of it, and whether it mattered.

    rows = message_log(bus.deliveries(), traces, start)    # one row per message per recipient
    summary(rows)                                           # counts, bytes, influence

AUV-07, 7.4: for each message, "creation time, scheduled delivery time,
actual delivery time, dropped-or-delivered status, sender and recipient,
size, expiration -- and WHETHER THE MESSAGE INFLUENCED A DECISION." The first
eight come from the bus's record of deliveries; the last from the
recipient's own decision trace, which only the experiment joins to it.

INFLUENCE, AT TWO LEVELS (Phase 7 plan, recommendation 5):

* IN THE BELIEF: the recipient made a decision while a team record built from
  this message was in its belief (the snapshot names the message). It could
  have mattered.
* READ BY THE POLICY: the recipient's policy looked at that record while
  deciding (`TraceEntry.read`). It did matter, in the only sense a rule
  policy can show.

A message that was never delivered can do neither, and the log says why it
was not: out of range, expired, or still pending when the flight ended -- and,
on Phase 10's network, lost, rate-limited or partitioned.

LIFETIMES (Phase 10, AUV-10 10.4). Two things the log checks, and one it counts:

* NEVER DELIVERED LATE (`late`, on the bus's own times): no message reaches its recipient at or after
  its lifetime's end. The bus guarantees it; the log shows it, flight by flight.
* NEVER CURRENT LATE (`current_late`): no team record past its lifetime is
  ever held as current in a decision's belief.
* STALE-MESSAGE DECISIONS (`stale_decisions`), AUV-10's diagnostic: decisions
  whose policy read a teammate's record already past its lifetime. Not an
  error in itself -- a relay flies toward a silent teammate's last known
  place on purpose -- but "a stale intent acted upon is worse than no intent
  at all", so each is counted and named.
Times are counted from `start`, the flight's beginning. Rows come in a fixed
order -- sent time, sender, sequence number, recipient -- since agents on
their own threads may send at the same instant in either order.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

ROUND = 3


def _json(entry: Any) -> dict[str, Any]:
    return entry if isinstance(entry, dict) else entry.as_json()


def _rel(t: float | None, start: float) -> float | None:
    return None if t is None else round(t - start, ROUND)


def message_log(deliveries: Iterable[Any], traces: dict[str, Iterable[Any]], start: float = 0.0) -> list[dict[str, Any]]:
    """One row per delivery -- a message to one recipient -- with its fate and its influence."""
    in_belief: dict[tuple[str, str], float] = {}            # (recipient, message id) -> first decision time
    read: dict[tuple[str, str], float] = {}
    for drone, trace in traces.items():
        for entry in map(_json, trace):
            for record in entry["belief"].get("team", {}).values():
                if isinstance(record, dict) and record.get("message_id"):
                    in_belief.setdefault((drone, record["message_id"]), entry["at"])
            for mid in entry.get("read", []):
                read.setdefault((drone, mid), entry["at"])
    rows = []
    for d in sorted(deliveries, key=lambda d: (d.sent_at, d.message.sender_id, d.message.sequence_number, d.recipient)):
        m = d.message
        key = (d.recipient, m.message_id)
        rows.append({
            "message_id": m.message_id, "type": m.message_type.value, "sender": m.sender_id,
            "recipient": d.recipient, "created_s": _rel(m.timestamp, start), "sent_s": _rel(d.sent_at, start),
            "scheduled_s": _rel(d.scheduled_at, start), "delivered_s": _rel(d.delivered_at, start),
            "status": d.status, "size_bytes": m.size_bytes(), "expires_s": _rel(m.expires_at, start),
            "distance_m": None if d.distance_m is None else round(d.distance_m, ROUND),
            "in_belief_at_s": _rel(in_belief.get(key), start), "read_by_policy_at_s": _rel(read.get(key), start),
        })
    return rows


def late(deliveries: Iterable[Any]) -> list[Any]:
    """Deliveries made at or after the message's lifetime ended -- on the bus's own times, not the log's
    rounded ones: there must be none."""
    return [d for d in deliveries if d.status == "delivered" and d.message.expired(d.delivered_at)]


def current_late(traces: dict[str, Iterable[Any]], start: float = 0.0) -> list[dict[str, Any]]:
    """Team records held as current in a decision's belief although past their lifetime: there must be none."""
    out = []
    for drone, trace in traces.items():
        for entry in map(_json, trace):
            for mate, record in entry["belief"].get("team", {}).items():
                if isinstance(record, dict) and record.get("current") and record.get("expires_in_s", 1.0) <= 0:
                    out.append({"drone": drone, "at_s": _rel(entry["at"], start), "teammate": mate,
                                "message_id": record.get("message_id")})
    return out


def stale_decisions(traces: dict[str, Iterable[Any]], start: float = 0.0) -> list[dict[str, Any]]:
    """Decisions whose policy read a teammate's record past its lifetime (AUV-10's diagnostic), in time order."""
    out = []
    for drone, trace in traces.items():
        for entry in map(_json, trace):
            read = set(entry.get("read", []))
            for mate, record in entry["belief"].get("team", {}).items():
                if isinstance(record, dict) and not record.get("current") and record.get("message_id") in read:
                    out.append({"drone": drone, "at_s": _rel(entry["at"], start), "teammate": mate,
                                "message_id": record["message_id"], "past_lifetime_s": -record["expires_in_s"],
                                "action": entry.get("action")})
    return sorted(out, key=lambda r: (r["at_s"], r["drone"], r["teammate"]))


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What the log adds up to: how many, of what, what became of them, how many mattered."""
    delivered = [r for r in rows if r["status"] == "delivered"]
    return {
        "deliveries": len(rows),
        "by_status": dict(sorted(Counter(r["status"] for r in rows).items())),
        "by_type": dict(sorted(Counter(r["type"] for r in rows).items())),
        "bytes_sent": sum(r["size_bytes"] for r in rows),
        "bytes_delivered": sum(r["size_bytes"] for r in delivered),
        "in_belief": sum(r["in_belief_at_s"] is not None for r in rows),
        "read_by_policy": sum(r["read_by_policy_at_s"] is not None for r in rows),
    }
