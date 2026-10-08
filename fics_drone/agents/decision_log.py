"""Phase 6 exit criterion: a log that records, for each decision, what the
agent knew AND what it did not - derived only from the belief object itself,
never from ground truth, so the log can never accidentally show more than
the agent actually had access to.
"""

import json
from dataclasses import asdict, dataclass
from typing import List

from .belief import Belief
from .objectives import Objective, ReplanEvent


@dataclass
class DecisionLogEntry:
    step: int
    t: float
    drone_name: str
    trigger: str
    knew: str
    did_not_know: str
    decided: str


class DecisionLogger:
    def __init__(self):
        self.entries: List[DecisionLogEntry] = []

    def record(self, step: int, drone_name: str, event: ReplanEvent, belief: Belief, objective: Objective):
        targets = list(belief.mission.targets_known.keys())
        knew = (f"pos={tuple(round(p, 1) for p in belief.position)} "
                f"battery={belief.battery_frac_remaining:.0%} "
                f"sector={belief.mission.sector_id} targets_known={targets}")
        sector_status = "not fully searched" if belief.search_queue else "search complete"
        target_status = "no targets observed yet" if not targets else "no other sectors observed"
        did_not_know = f"sector {belief.mission.sector_id} {sector_status}; {target_status}"
        decided = f"{objective.value} (phase={belief.phase})"
        entry = DecisionLogEntry(step=step, t=belief.elapsed_s, drone_name=drone_name,
                                  trigger=event.value, knew=knew, did_not_know=did_not_know, decided=decided)
        self.entries.append(entry)
        return entry

    def format_entry(self, e: DecisionLogEntry) -> str:
        return (f"[step {e.step} t={e.t:.1f}s] {e.drone_name} triggers={e.trigger}\n"
                f"    KNEW        : {e.knew}\n"
                f"    DID NOT KNOW: {e.did_not_know}\n"
                f"    DECIDED     : {e.decided}")

    def print_all(self):
        for e in self.entries:
            print(self.format_entry(e))

    def to_json(self, path: str):
        with open(path, "w") as f:
            json.dump([asdict(e) for e in self.entries], f, indent=2)
