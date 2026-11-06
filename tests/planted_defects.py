"""Phase 16's planted defects (AUV-15 exit): realistic coordination and communication defects, one at a time.

Fixed 2026-11-06 before they were first run, with the bar: at least 90 % discovered by the simulator-free
tests in TESTS. Each is (file, the text replaced, what replaces it, what the defect does). `scripts/testing_exit.py`
plants each in a throwaway copy of the repository and runs TESTS until one fails.
"""

TESTS = [
    "test_messages.py",
    "test_message_bus.py",
    "test_lifetimes.py",
    "test_network.py",
    "test_bids.py",
    "test_tasks.py",
    "test_contract_net.py",
    "test_health.py",
    "test_roles.py",
    "test_belief_state.py",
    "test_keepout.py",
    "test_recovery_policy.py",
    "test_team_policy.py",
    "test_link_health.py",
    "test_agents_talk.py",
    "test_integration_mock.py"
]

DEFECTS = [
    ("agentic_uav/simulator/message_bus.py", "                if self.range_m is None or d <= self.range_m:", "                if True:", "range ignored"),
    ("agentic_uav/simulator/message_bus.py", "now + self.delay_s, PENDING", "now, PENDING", "no delay"),
    ("agentic_uav/simulator/message_bus.py", "        if not tx.admit(now):", "        if False:", "no rate limit"),
    ("agentic_uav/simulator/message_bus.py", "            if net.range_m is not None and d > net.range_m:", "            if False:", "network range ignored"),
    ("agentic_uav/simulator/message_bus.py", "            elif net.partitioned(drone, r, since):", "            elif False:", "partitions ignored"),
    ("agentic_uav/simulator/message_bus.py", "                if lost:", "                if False:", "losses ignored"),
    ("agentic_uav/simulator/message_bus.py", "left + latency, PENDING", "left, PENDING", "no latency"),
    ("agentic_uav/simulator/message_bus.py", "ready = [d for d in self._inbox[drone] if d.scheduled_at <= now]", "ready = [d for d in self._inbox[drone] if d.scheduled_at <= now + 1.0]", "read early"),
    ("agentic_uav/simulator/message_bus.py", "                if d.message.expired(now):", "                if False:", "stale news read"),
    ("agentic_uav/simulator/message_bus.py", "key=lambda m: (m.timestamp, m.sender_id, m.sequence_number)", "key=lambda m: (m.timestamp, m.sequence_number)", "order not total"),
    ("agentic_uav/simulator/message_bus.py", "return AgentMessage.from_json(json.loads(json.dumps(message.as_json())))", "return message", "shared, not a copy"),
    ("agentic_uav/simulator/network.py", "        return u < self.loss_probability, latency", "        return u < self.loss_probability / 2, latency", "half the losses"),
    ("agentic_uav/simulator/network.py", "max(self.latency_floor_s, self.latency_mean_s + self.latency_jitter_s * g)", "self.latency_mean_s + self.latency_jitter_s * g", "no floor"),
    ("agentic_uav/simulator/network.py", "return self.start_s - PARTITION_TOL_S < t_s < self.end_s - PARTITION_TOL_S", "return self.start_s - PARTITION_TOL_S < t_s", "never heals"),
    ("agentic_uav/simulator/network.py", "        self.busy_until = begin + size_bytes / bw", "        self.busy_until = now", "no bandwidth"),
    ("agentic_uav/simulator/network.py", "        self.tokens = min(rate, self.tokens + (now - self.refilled_at) * rate)", "        self.tokens = rate", "bucket never empties"),
    ("agentic_uav/core/messages.py", "        return now >= self.expires_at - EXPIRY_TOL_S", "        return now > self.expires_at + EXPIRY_TOL_S", "expiry boundary"),
    ("agentic_uav/core/messages.py", "    problems = payload_problems(message_type, payload)", "    problems = []", "malformed payloads accepted"),
    ("agentic_uav/coordination/tasks.py", "        return self.status is TaskStatus.CLAIMED and now >= self.lease_expires_at", "        return self.status is TaskStatus.CLAIMED and now > self.lease_expires_at + 5.0", "late lease"),
    ("agentic_uav/coordination/tasks.py", "return replace(self, status=TaskStatus.CLAIMED, assigned_agent=agent, lease_expires_at=at + lease_s)", "return replace(self, status=TaskStatus.CLAIMED, assigned_agent=agent, lease_expires_at=at + 2 * lease_s)", "long first lease"),
    ("agentic_uav/coordination/contract_net.py", "self.book.update(t.renewed(message.timestamp, self.config.lease_s), now,", "self.book.update(t, now,", "progress never renews"),
    ("agentic_uav/coordination/contract_net.py", "            if t.lease_expired(now) and t.assigned_agent != self.owner:", "            if t.lease_expired(now):", "re-announces its own task"),
    ("agentic_uav/coordination/contract_net.py", "now >= self.round_started_at + self.config.bid_window_s - EPS", "now >= self.round_started_at - EPS", "no bid window"),
    ("agentic_uav/coordination/contract_net.py", "    return (round(value, CLAIM_RANKING), who)", "    return (round(value, CLAIM_RANKING), \"\")", "ties unbroken"),
    ("agentic_uav/coordination/contract_net.py", "        best = min(claims, key=lambda who: _key(claims[who][0], who))", "        best = max(claims, key=lambda who: _key(claims[who][0], who))", "worst claim wins"),
    ("agentic_uav/coordination/bids.py", "    D = (to_task + through) / me.speed_mps", "    D = through / me.speed_mps", "distance to the task ignored"),
    ("agentic_uav/coordination/bids.py", "    left = me.battery - cost", "    left = me.battery", "battery not costed"),
    ("agentic_uav/coordination/health.py", "        if silence >= self.failed_s:", "        if silence >= 10 * self.failed_s:", "never failed"),
    ("agentic_uav/coordination/health.py", "        if silence >= self.unreachable_s:", "        if silence > self.unreachable_s + 5:", "late unreachable"),
    ("agentic_uav/coordination/health.py", "            if heard is not None and heard > self._last[m]:", "            if False:", "never heard again"),
    ("agentic_uav/coordination/health.py", "            if LADDER.index(rung) > LADDER.index(current):", "            if True:", "ladder steps down"),
    ("agentic_uav/coordination/roles.py", "    if holding is not None:\n        return Role.SCOUT", "    if holding is not None and not unreachable:\n        return Role.SCOUT", "drops its task to relay"),
    ("agentic_uav/agents/recovery_policy.py", "self.detector.in_state(Health.UNREACHABLE))", "self.detector.in_state(Health.UNREACHABLE, Health.FAILED))", "relays toward the dead"),
    ("agentic_uav/coordination/keepout.py", "if now - at >= cfg.after_s - 1e-9 and alt >= cfg.min_altitude_m]", "if now - at >= 0 and alt >= cfg.min_altitude_m]", "keeps out of the living"),
    ("agentic_uav/coordination/keepout.py", "return abs(point[0] - centre[0]) <= reach_m and abs(point[1] - centre[1]) <= reach_m", "return abs(point[0] - centre[0]) <= reach_m or abs(point[1] - centre[1]) <= reach_m", "a cross, not a square"),
    ("agentic_uav/agents/belief_state.py", "        left = 1.0 - self.age(now) / self.report.ttl_s", "        left = 1.0", "confidence never falls"),
    ("agentic_uav/agents/belief_state.py", "        return self.report.at + self.report.ttl_s", "        return self.report.at + 2 * self.report.ttl_s", "records live twice as long"),
]
