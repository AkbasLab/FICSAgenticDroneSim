"""Mission metrics. Placeholder for the experimental phase.

Will compute the outcomes the study cares about - mission continuity, task
completion, behavior under communication degradation and agent loss - so
architectures (centralized vs decentralized vs independent) can be compared.
"""


def summarize(results):
    """Baseline placeholder: just count how many drones finished."""
    finished = sum(1 for r in results.values() if not isinstance(r, Exception))
    return {"drones": len(results), "finished": finished}
