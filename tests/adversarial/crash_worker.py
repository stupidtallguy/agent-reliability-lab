"""Hard process boundary for a synthetic lost-response restart test."""

import asyncio
import json
import os
import sys

from agent_reliability_lab.agent.config import AgentConfig
from agent_reliability_lab.agent.execution import AgentExecution
from agent_reliability_lab.opsdesk.database import engine_from_env


async def main():
    engine = engine_from_env()
    host = AgentExecution(engine)
    execution_id = sys.argv[2]
    config = AgentConfig.model_validate_json(json.dumps(host.store.get(execution_id)["config"]))

    def crash(operation, response):
        if operation["tool"] == "create_task":
            os._exit(29)

    result = await host.run(
        execution_id, config, after_dispatch=crash if sys.argv[1] == "crash" else None
    )
    print(result.model_dump_json())
    engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
