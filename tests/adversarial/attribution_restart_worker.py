"""Crash a test-owned update after its actual MCP commit, before acknowledgement."""

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
    identifier = sys.argv[2]
    config = AgentConfig.model_validate_json(json.dumps(host.store.get(identifier)["config"]))

    def crash(operation, response):
        if operation["tool"] == "update_task":
            os._exit(29)

    result = await host.run(
        identifier, config, after_dispatch=crash if sys.argv[1] == "crash" else None
    )
    print(result.model_dump_json())
    engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
