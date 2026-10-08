"""Phase 10: agents estimate link quality, they never read it. An agent has
no access to a NetworkModel or NetworkProfile - this class only ever sees
the Message objects that actually arrived (plus wall-clock `now` at read
time) and infers from there: a gap in a sender's sequence numbers means
something never arrived at all, and the age of a message when it's finally
read is dominated by how often this agent checks its inbox, not by the wire -
which is exactly the number that matters for deciding whether the contents
can still be trusted.
"""

from typing import Dict, List, Optional

from ..coordination.protocols import Message, MessageType


class CommsEstimator:
    def __init__(self):
        self._last_seq: Dict[str, int] = {}
        self._received: Dict[str, int] = {}
        self._gaps: Dict[str, int] = {}
        self._heartbeats_received: Dict[str, int] = {}
        self._ages: Dict[str, List[float]] = {}

    def observe(self, msg: Message, now: float):
        sender = msg.sender
        self._received[sender] = self._received.get(sender, 0) + 1
        self._ages.setdefault(sender, []).append(max(0.0, now - msg.created_t))
        if msg.type == MessageType.HEARTBEAT:
            self._heartbeats_received[sender] = self._heartbeats_received.get(sender, 0) + 1

        last = self._last_seq.get(sender)
        if last is not None and msg.seq > last + 1:
            self._gaps[sender] = self._gaps.get(sender, 0) + (msg.seq - last - 1)
        if last is None or msg.seq > last:
            self._last_seq[sender] = msg.seq

    def estimated_loss_rate(self, sender: str) -> Optional[float]:
        """Fraction of this sender's messages estimated never to have
        arrived at all - inferred purely from sequence gaps, since a
        delayed-but-arrived message never shows up as one."""
        received = self._received.get(sender, 0)
        gaps = self._gaps.get(sender, 0)
        expected = received + gaps
        if expected == 0:
            return None
        return gaps / expected

    def mean_message_age(self, sender: str) -> Optional[float]:
        """NOT a latency estimate - this is message age on arrival, which is
        dominated by this agent's own decision cadence (how long between
        inbox checks), not by the wire. A true one-way latency estimate
        would need an echo protocol and a synchronised clock, neither of
        which exists here."""
        ages = self._ages.get(sender)
        if not ages:
            return None
        return sum(ages) / len(ages)

    def heartbeats_received(self, sender: str) -> int:
        return self._heartbeats_received.get(sender, 0)
