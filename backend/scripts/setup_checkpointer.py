"""Create the LangGraph checkpointer's tables (saved agent state per conversation).

Safe to run again: it only applies what is missing. Runs at deploy time as part of
`uv run poe migrate`, not on app startup.
"""

from langgraph.checkpoint.postgres import PostgresSaver
from loguru import logger

from backend.core.config import get_psycopg_url


def main() -> None:
    with PostgresSaver.from_conn_string(get_psycopg_url()) as checkpointer:
        checkpointer.setup()
    logger.info("Checkpointer tables are up to date")


if __name__ == "__main__":
    main()
