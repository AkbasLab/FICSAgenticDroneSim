"""Inter-agent message bus. Placeholder for the multi-agent phase.

Will let agents publish/subscribe to structured messages (task offers, status,
role changes). Delivery will pass through network_model so latency and loss
apply. The open-loop baseline has no messaging.
"""


class MessageBus:
    def publish(self, sender: str, topic: str, payload) -> None:
        raise NotImplementedError("messaging is part of the next phase")

    def subscribe(self, vehicle_id: str, topic: str) -> None:
        raise NotImplementedError("messaging is part of the next phase")
