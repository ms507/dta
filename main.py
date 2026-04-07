import sys

from config import Config
from agent import TradingAgent
from utils.logger import get_logger

logger = get_logger("Main")


def main() -> None:
    config = Config()
    try:
        config.validate()
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    if not config.testnet:
        logger.warning("=" * 60)
        logger.warning("  LIVE TRADING MODE — real funds will be used!")
        logger.warning("  Press Ctrl+C within 5 seconds to abort.")
        logger.warning("=" * 60)
        import time
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Aborted by user.")
            sys.exit(0)

    agent = TradingAgent(config)
    agent.run()


if __name__ == "__main__":
    main()
