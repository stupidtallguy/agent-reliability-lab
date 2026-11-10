from agent_reliability_lab.evaluation.reporting import report
from tests.remediation17.support import facts, store


class MemoryView:
    def __init__(self):
        self.trial_value, result = facts()
        self.store = store([(self.trial_value, result)])
        self.document = report(self.store, "a" * 32, evaluator_version="1.7.0")

    def counts(self):
        return dict(experiments=1, trials=1, scores=1, reports=1)

    def rows(self, resource, **kwargs):
        return {
            "experiments": [self.store.record],
            "reports": [{"report_id": "b" * 32}],
            "trials": [self.trial_value],
        }.get(resource, [])

    def report(self, _):
        return self.document

    def trial(self, _):
        return self.trial_value

    def readiness(self, _):
        return dict(human_declared_attestations=0, held_out_count=0, approval="pending")


def app():
    from agent_reliability_lab.dashboard.app import render
    from tests.dashboard.support import MemoryView

    render(MemoryView())
