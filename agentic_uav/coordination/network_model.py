"""Communication degradation model. Placeholder.

Will introduce latency, packet loss, bandwidth limits and temporary partitions
between agents, so we can test that the team keeps operating when it can't
communicate reliably.
"""


class NetworkModel:
    def deliver(self, message) -> bool:
        """Decide whether/when a message is delivered. Currently a no-op."""
        return True
