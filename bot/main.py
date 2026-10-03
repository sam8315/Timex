"""
نقطه ورود ربات بله
اجرا: python -m bot.main
"""
import logging
import time
import sys

from core.logging_config import configure_logging
from bot import bale_api
from bot.config import POLLING_TIMEOUT
from bot.handlers import handle_message

logger = logging.getLogger(__name__)


def main():
    configure_logging("bale")

    logger.info(
        "Bale bot process starting",
        extra={"event": "service.starting"},
    )

    # بررسی اتصال به ربات
    bot_info = bale_api.get_me()
    if not bot_info.get('ok'):
        logger.critical(
            "Bot connection failed; check BALE_BOT_TOKEN in .env",
            extra={"event": "service.stopping"},
        )
        sys.exit(1)

    bot_name = bot_info.get('result', {}).get('username', 'unknown')
    logger.info(
        "Bot connected username=%s",
        bot_name,
        extra={"event": "bot.connected"},
    )
    logger.info(
        "Starting polling timeout=%ss",
        POLLING_TIMEOUT,
        extra={"event": "bot.polling_started"},
    )

    offset = 0
    consecutive_loop_errors = 0

    try:
        while True:
            try:
                updates = bale_api.get_updates(offset=offset, timeout=POLLING_TIMEOUT)

                if consecutive_loop_errors > 0:
                    logger.info(
                        "Polling loop recovered after %s consecutive errors",
                        consecutive_loop_errors,
                        extra={"event": "bot.polling_started"},
                    )
                    consecutive_loop_errors = 0

                for update in updates:
                    offset = update.get('update_id', 0) + 1

                    message = update.get('message')
                    if message:
                        try:
                            handle_message(message)
                        except Exception:
                            logger.exception(
                                "Message handler failed update_id=%s",
                                update.get('update_id'),
                                extra={"event": "bot.api_call"},
                            )

            except KeyboardInterrupt:
                raise
            except Exception as exc:
                consecutive_loop_errors += 1
                error_type = type(exc).__name__
                if consecutive_loop_errors == 1:
                    logger.exception(
                        "Polling loop error error_type=%s",
                        error_type,
                        extra={"event": "bot.polling_error"},
                    )
                else:
                    logger.warning(
                        "Polling loop transient failure error_type=%s consecutive=%s",
                        error_type,
                        consecutive_loop_errors,
                        extra={"event": "bot.polling_error"},
                    )
                time.sleep(5)

            time.sleep(0.5)

    except KeyboardInterrupt:
        logger.info(
            "Bale bot stopped",
            extra={"event": "service.stopping"},
        )


if __name__ == "__main__":
    main()
