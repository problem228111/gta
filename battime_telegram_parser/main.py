import logging
import os
import time
from datetime import datetime

from dotenv import load_dotenv

from database import Database
from parser import BattimeParser
from telegram_bot import TelegramBot


load_dotenv()

SITE_URL = os.getenv("SITE_URL", "https://battime.ru/")
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
DB_PATH = os.getenv("DB_PATH", "news.db")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

ROSTOV_ONLY = os.getenv("ROSTOV_ONLY", "1").strip() == "1"
KEYWORDS = [
    x.strip()
    for x in os.getenv("KEYWORDS", "").split(",")
    if x.strip()
]

MAX_ARTICLE_CHARS = int(os.getenv("MAX_ARTICLE_CHARS", "0"))
ADD_SOURCE_LINK = os.getenv("ADD_SOURCE_LINK", "1").strip() == "1"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def validate_config():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в .env")
    if not CHANNEL_ID:
        raise RuntimeError("Не задан CHANNEL_ID в .env")


def process_once(parser: BattimeParser, db: Database, bot: TelegramBot):
    items = parser.get_news_list(
        rostov_only=ROSTOV_ONLY,
        keywords=KEYWORDS,
    )

    if not items:
        logging.warning("Не удалось найти свежую новость.")
        return

    item = items[0]
    logging.info("Свежая новость: %s | %s", item.title, item.url)

    if db.exists(item.url):
        logging.info("Новость уже отправлялась: %s", item.url)
        return

    article = parser.get_article(item)

    if not article.text:
        logging.warning("Текст статьи не найден: %s", item.url)
        return

    logging.info(
        "Найдена статья: %s | image=%s | chars=%s",
        article.title,
        bool(article.image_url),
        len(article.text),
    )

    bot.send_news(
        title=article.title,
        text=article.text,
        url=article.url,
        image_url=article.image_url,
        add_source_link=ADD_SOURCE_LINK,
        max_chars=MAX_ARTICLE_CHARS,
    )

    db.save(
        url=article.url,
        title=article.title,
        sent_at=datetime.now().isoformat(),
    )

    logging.info("Опубликовано в Telegram.")


def main():
    validate_config()

    parser = BattimeParser(
        base_url=SITE_URL,
        timezone=TIMEZONE,
    )
    db = Database(DB_PATH)
    bot = TelegramBot(BOT_TOKEN, CHANNEL_ID)

    logging.info("Бот запущен.")
    logging.info("Сайт: %s", SITE_URL)
    logging.info("Проверка каждые %s сек.", CHECK_INTERVAL)
    logging.info("Ростовский фильтр: %s", ROSTOV_ONLY)

    while True:
        try:
            process_once(parser, db, bot)
        except KeyboardInterrupt:
            logging.info("Остановка.")
            break
        except Exception:
            logging.exception("Ошибка при обработке. Повтор через интервал.")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
