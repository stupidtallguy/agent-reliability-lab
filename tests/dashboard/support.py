from agent_reliability_lab.evaluation.reporting import report
from tests.remediation17.support import facts, store


class MemoryView:
    def __init__(self):
        self.trial_value, result = facts()
        self.trial_value["experiment_id"] = result.experiment_id
        self.store = store([(self.trial_value, result)])
        self.document = report(self.store, "a" * 32, evaluator_version="1.7.0")

    def experiment_inventory(self, **kwargs):
        return [
            {
                "experiment_id": "a" * 32,
                "configuration": "baseline",
                "evaluator": "1.7.0",
                "cases": [{"scenario_id": "attack_hijack"}],
                "trial_count": 1,
                "has_report": True,
            }
        ]

    def report_index(self, experiment_id):
        return [{"report_id": self.document["report_id"], "evaluator": "1.7.0"}]

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

    def experiment(self, _):
        return self.store.record

    def trial(self, _):
        return self.trial_value


def app():
    from agent_reliability_lab.dashboard.app import render
    from tests.dashboard.support import MemoryView

    render(MemoryView())
