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
was not: out of range, expired, or still pending when the flight ended.
Times are counted from `start`, the flight's beginning.
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
    for d in deliveries:
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
