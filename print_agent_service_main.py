import logging

from printer_agent.agent import run_loop


logger = logging.getLogger("print_agent.service")


def main() -> None:
    try:
        run_loop()
    except KeyboardInterrupt:
        logger.info("Print Agent service stop requested; exiting cleanly.")


if __name__ == "__main__":
    main()
