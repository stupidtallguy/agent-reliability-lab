"""Subprocess boundary for restart tests; never invoked by an MCP model tool."""

import asyncio
import os
import sys

from agent_reliability_lab.agent.config import AgentConfig
from agent_reliability_lab.agent.execution import AgentExecution
from agent_reliability_lab.opsdesk.database import engine_from_env


async def main():
    engine = engine_from_env()
    host = AgentExecution(engine)
    execution_id = sys.argv[2]
    config = AgentConfig.model_validate(host.store.get(execution_id)["config"])

    def crash_after_commit(operation, response):
        if not response.get("error"):
            os._exit(23)

    result = await host.run(
        execution_id, config, after_dispatch=crash_after_commit if sys.argv[1] == "crash" else None
    )
    print(result.model_dump_json())
    engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
