import os
import logging
from typing import Dict

from printer_agent.agent import run_loop


logger = logging.getLogger("print_agent.service")


def get_print_agent_config() -> Dict[str, str]:
    return {
        "agent_module": "printer_agent.agent",
        "agent_id": os.getenv("AGENT_ID", "PC-PRINT-AGENT-01"),
        "print_engine": os.getenv("PRINT_ENGINE", "SUMATRA").upper(),
        "workdir": os.getenv("PRINT_WORKDIR", "print_out"),
        "printer_name": os.getenv("PRINTER_NAME", ""),
        "sumatra_path": os.getenv("SUMATRA_PATH", ""),
    }


def main() -> None:
    try:
        run_loop()
    except KeyboardInterrupt:
        logger.info("Print Agent service stop requested; exiting cleanly.")


if __name__ == "__main__":
    main()
