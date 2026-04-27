import logging
from app.db.database import init_database

from telegram.ext import (
    AIORateLimiter,
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.bot.handlers import (
    help_handler,
    message_handler,
    option_callback_handler,
    start_handler,
    stats_handler,
)

from app.config import settings


from app.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def build_app() -> Application:
    settings.validate()

    application = (
        Application.builder()
        .token(settings.BOT_TOKEN)
        .rate_limiter(AIORateLimiter())
        .build()
    )

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CallbackQueryHandler(option_callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    return application


def main() -> None:
    setup_logging("bot.log")

    logger.info("Initializing database...")
    init_database()

    logger.info("Starting bot...")
    application = build_app()
    application.run_polling()


if __name__ == "__main__":
    main()