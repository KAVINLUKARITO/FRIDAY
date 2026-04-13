from __future__ import annotations


class FridayIdentity:
    NAME = "Friday"
    VERSION = "2.0.0"
    DESCRIPTION = "AGI-Progressive Autonomous Task Agent"

    BANNER = """

          FRIDAY  AI Agent System
          Production Task Runner
          AGI-Progressive Task Agent
          Production Grade | v2.0.0

    """

    @classmethod
    def introduce(cls, memory_stats: dict, knowledge_stats: dict) -> str:
        completed = int(memory_stats.get("completed", 0))
        total = int(memory_stats.get("total_episodes", 0))
        nodes = int(knowledge_stats.get("total_nodes", 0))
        return (
            f"I am {cls.NAME}. I have completed {completed} of "
            f"{total} tasks and hold {nodes} knowledge nodes. "
            f"How can I help?"
        )
