"""Bounded read-only data boundary for future presentation clients; no UI or scoring."""

import sqlalchemy as sa

from agent_reliability_lab.agent import tables as a
from agent_reliability_lab.evaluation import tables as e
from agent_reliability_lab.research.persistence import artifacts


class ResearchView:
    def __init__(self, engine):
        self.engine = engine

    def rows(self, resource, *, identifier=None, kind=None, limit=50, offset=0):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid read-only pagination bounds")
        registry = dict(
            experiments=(e.experiments, "experiment_id"),
            trials=(e.trials, "experiment_id"),
            scores=(e.scores, "trial_id"),
            reports=(e.reports, "experiment_id"),
            report_manifests=(e.report_manifests, "report_id"),
            artifacts=(artifacts, "scope"),
            traces=(a.events, "execution_id"),
            provenance=(a.provenance, "execution_id"),
        )
        if resource not in registry:
            raise ValueError("unknown read-only research resource")
        table, key = registry[resource]
        query = sa.select(table)
        if identifier is not None:
            query = query.where(table.c[key] == identifier)
        if kind is not None:
            if resource != "artifacts":
                raise ValueError("kind applies only to research artifacts")
            query = query.where(table.c.kind == kind)
        with self.engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            return [
                dict(row)
                for row in connection.execute(
                    query.order_by(*table.primary_key.columns).limit(limit).offset(offset)
                ).mappings()
            ]
