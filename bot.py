import re
import time
import signal
import sys
import logging
import threading
from datetime import datetime

# Ensure UTF-8 stdout on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import config
from storage import NewsSeenTracker, SubscriberManager
from news_sources import (
    detect_news_category,
    TRUSTED_NEWS_SOURCES,
    CATEGORY_ICONS_AND_TITLES,
)
from news_fetcher import fetch_latest_news
from formatter import format_news_card
from telegram_client import TelegramClient

# Setup logging
log_level = getattr(logging, config.LOG_LEVEL, logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("NewsAI-Bot")

# Suppress verbose internal SDK logs
logging.getLogger("google_genai").setLevel(logging.ERROR)
logging.getLogger("google_genai.models").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


# Initialize core services
tracker = NewsSeenTracker(config.NEWS_SEEN_FILE, max_items=config.MAX_SEEN_HISTORY)
subscribers = SubscriberManager(config.SUBSCRIBERS_FILE)
tg = TelegramClient()
running = True
bot_username = ""
_alert_lock = threading.Lock()


def signal_handler(signum, frame):
    global running
    sig_name = "SIGINT (Ctrl+C)" if signum == signal.SIGINT else f"Signal {signum}"
    logger.info(f"Received {sig_name}. Gracefully shutting down...")
    running = False


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, signal_handler)


def seed_existing_news():
    """
    On the very first run, mark current top news as seen so we don't spam
    old news to subscribers.
    """
    if config.SEED_ON_FIRST_RUN and tracker.total_seen() == 0:
        logger.info("First run detected: Seeding baseline news to database...")
        for cat in config.ALERT_CATEGORIES:
            try:
                items = fetch_latest_news(category=cat, max_items=10, require_image=False)
                added = tracker.mark_many(items)
                logger.info(f"Seeded {added} baseline items for [{cat}].")
            except Exception as e:
                logger.warning(f"Error seeding category {cat}: {e}")
        logger.info(f"Seeding completed. Total registered baseline items: {tracker.total_seen()}")


def check_and_alert_news() -> int:
    """
    Scans configured categories for new articles and broadcasts alerts to Telegram Channels
    and active 1-on-1 subscribers.
    - Uses _alert_lock to prevent any overlapping / duplicate background cycles.
    - Uses tracker.is_seen(item_id, title=title_en) to prevent duplicate / double news across multiple feeds.
    - Sends ONLY big/breaking news (skips minor filler when ONLY_BIG_NEWS is True).
    - Sends ONLY articles with valid photo cards (when REQUIRE_PHOTO_CARD is True).
    - Limits total alerts per cycle to MAX_ALERTS_PER_CYCLE.
    """
    if not _alert_lock.acquire(blocking=False):
        logger.debug("Alert cycle already in progress. Skipping to prevent duplicate sends.")
        return 0

    try:
        target_channels = config.TELEGRAM_CHANNEL_IDS if config.BROADCAST_TO_CHANNEL else []
        target_subscribers = subscribers.get_active_subscribers() if config.BROADCAST_TO_SUBSCRIBERS else []

        if not target_channels and not target_subscribers:
            logger.debug("No channels or active subscribers registered. News will be marked seen silently.")

        alerts_sent = 0
        for cat in config.ALERT_CATEGORIES:
            if not running:
                break

            # Check cycle limit
            if alerts_sent >= config.MAX_ALERTS_PER_CYCLE:
                logger.info(f"Cycle alert limit reached ({alerts_sent}/{config.MAX_ALERTS_PER_CYCLE}). Pausing until next cycle.")
                break

            try:
                items = fetch_latest_news(
                    category=cat,
                    max_items=config.MAX_ITEMS_PER_CHECK,
                    require_image=config.REQUIRE_PHOTO_CARD
                )

                for item in items:
                    if not running or alerts_sent >= config.MAX_ALERTS_PER_CYCLE:
                        break

                    item_id = item.get("id")
                    title_en = item.get("title_en", "")
                    article_link = item.get("link", "")

                    # Comprehensive 4-layer deduplication check: check ID, normalized URL, exact title, and fuzzy title
                    if not item_id or tracker.is_seen(item_id, title=title_en, url=article_link):
                        continue

                    image_url = item.get("image_url")

                    # If photo card is required and no image is available, skip
                    if config.REQUIRE_PHOTO_CARD and (not image_url or not image_url.startswith(("http://", "https://"))):
                        logger.info(f"Skipping article without photo card [{cat}]: {title_en}")
                        tracker.mark_seen(item_id, title=title_en, source=item.get("source", ""), url=article_link)
                        continue

                    # Format and evaluate if Big News
                    card_text = format_news_card(item, translate_to_khmer=config.TRANSLATE_TO_KHMER)
                    if not card_text or len(card_text.strip()) < 30:
                        logger.info(f"Skipping article (filtered as non-major or invalid): {title_en}")
                        tracker.mark_seen(item_id, title=title_en, source=item.get("source", ""), url=article_link)
                        continue

                    logger.info(f"🚨 BIG NEWS APPROVED [{cat}]: {title_en}")

                    # Build inline keyboard button for direct article link if enabled
                    button_markup = None
                    if config.CHANNEL_ENABLE_BUTTONS and article_link:
                        button_markup = tg.build_read_more_keyboard(article_link)

                    # 1. Broadcast to Telegram Channels
                    ch_sent_count = 0
                    for ch_id in target_channels:
                        ch_ok = False
                        if image_url and config.SEND_PHOTO:
                            ch_ok = tg.send_photo(
                                ch_id,
                                image_url,
                                card_text,
                                fallback_to_text=not config.REQUIRE_PHOTO_CARD,
                                reply_markup=button_markup
                            )
                        elif not config.REQUIRE_PHOTO_CARD:
                            ch_ok = tg.send_message(
                                ch_id,
                                card_text,
                                reply_markup=button_markup
                            )

                        if ch_ok:
                            ch_sent_count += 1
                        else:
                            logger.warning(f"Failed to deliver alert to channel '{ch_id}': {tg.last_error_description}")
                        time.sleep(0.3)

                    # 2. Broadcast to active 1-on-1 public subscribers
                    sub_sent_count = 0
                    for target_id in list(target_subscribers):
                        sub_ok = False
                        if image_url and config.SEND_PHOTO:
                            sub_ok = tg.send_photo(
                                target_id,
                                image_url,
                                card_text,
                                fallback_to_text=not config.REQUIRE_PHOTO_CARD,
                                reply_markup=button_markup
                            )
                        elif not config.REQUIRE_PHOTO_CARD:
                            sub_ok = tg.send_message(
                                target_id,
                                card_text,
                                reply_markup=button_markup
                            )

                        if sub_ok:
                            sub_sent_count += 1
                        else:
                            if tg.is_user_blocked():
                                logger.info(f"Subscriber {target_id} blocked bot or chat unavailable. Deactivating subscriber.")
                                subscribers.deactivate(target_id, reason=tg.last_error_description)

                        time.sleep(0.05)

                    tracker.mark_seen(item_id, title=title_en, source=item.get("source", ""), url=article_link)
                    alerts_sent += 1
                    logger.info(
                        f"Dispatched Tech News Alert ({alerts_sent}/{config.MAX_ALERTS_PER_CYCLE}) -> "
                        f"Channels: {ch_sent_count}/{len(target_channels)}, "
                        f"Subscribers: {sub_sent_count}/{len(target_subscribers)}: {title_en}"
                    )
                    time.sleep(2.0)

            except Exception as e:
                logger.error(f"Error during news check for category '{cat}': {e}", exc_info=True)

        return alerts_sent
    finally:
        _alert_lock.release()


def news_alert_loop():
    """
    Background worker loop that periodically checks for news.
    """
    mode_desc = "Big News Only" if config.ONLY_BIG_NEWS else "All Technology News"
    logger.info(f"News Alert Worker started. Checking every {config.POLL_INTERVAL_SECONDS}s (Max {config.MAX_ALERTS_PER_CYCLE} alerts/cycle, Mode: {mode_desc})...")
    while running:
        try:
            sent = check_and_alert_news()
            if sent > 0:
                logger.info(f"Alert cycle complete: {sent} tech news card(s) dispatched.")
            else:
                logger.info("Alert cycle complete: No new technology news found.")
        except Exception as e:
            logger.error(f"Unexpected error in alert loop: {e}")

        # Sleep interval with interruptible polling
        for _ in range(max(1, config.POLL_INTERVAL_SECONDS)):
            if not running:
                break
            time.sleep(1)


def handle_user_command(chat_id: int or str, text: str, user_info: dict = None):
    """
    Handles user interaction:
    - Welcomes user only (no command menu, no double sending).
    - Subscribes user for automated 24/7 background technology alerts.
    - Avoids duplicate greetings if user is already connected.
    """
    text = (text or "").strip()
    user_info = user_info or {}
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "")

    # Quiet opt-out if explicitly requested
    if text.lower() in ("/stop", "/unsubscribe", "stop", "unsubscribe"):
        subscribers.remove_subscriber(chat_id)
        tg.send_message(chat_id, "🔕 បានបិទការជូនដំណឹង (Unsubscribed)។")
        return

    # Check if newly subscribing
    is_new = subscribers.add_subscriber(chat_id, username=username, first_name=first_name)
    display_name = first_name or username or "មិត្តអ្នកអាន"

    if is_new or text.lower() in ("/start", "start"):
        # Send welcome message once
        welcome_msg = (
            f"👋 <b>សូមស្វាគមន៍ {display_name} មកកាន់ប្រព័ន្ធព័ត៌មានបច្ចេកវិទ្យា (Technology News)!</b>\n"
            "───────────────────────────\n"
            "🤖 ប្រព័ន្ធនេះនឹងផ្ញើជូនលោកអ្នកនូវព័ត៌មានបច្ចេកវិទ្យាថ្មីៗ និងសំខាន់ៗបំផុត (AI, Gadgets, Computers, Mobile, Hardware) ជាទម្រង់ Photo Card ភាសាខ្មែរដោយស្វ័យប្រវត្ត 24/7។"
        )
        tg.send_message(chat_id, welcome_msg)
    else:
        # Already subscribed, polite single confirmation
        tg.send_message(
            chat_id,
            "✅ <b>លោកអ្នកបានភ្ជាប់រួចរាល់ហើយ!</b>\n"
            "ប្រព័ន្ធកំពុងតាមដានព័ត៌មានបច្ចេកវិទ្យា 24/7 ហើយនឹងផ្ញើជូនលោកអ្នកភ្លាមៗពេលមានព័ត៌មានថ្មីចេញផ្សាយ។"
        )


# Admin caching for fast moderation lookup without Telegram rate limit hits
_chat_admins_cache = {}
_chat_admins_time = {}


def is_chat_admin(chat_id: int or str, user_id: int or str) -> bool:
    """
    Checks if a user is an administrator in the given chat (cached for 5 minutes).
    """
    now = time.time()
    cid_key = str(chat_id)
    if cid_key in _chat_admins_cache and (now - _chat_admins_time.get(cid_key, 0)) < 300:
        return user_id in _chat_admins_cache[cid_key]

    admins = tg.get_chat_administrators(chat_id)
    if admins:
        _chat_admins_cache[cid_key] = set(admins)
        _chat_admins_time[cid_key] = now
        return user_id in _chat_admins_cache[cid_key]
    return False


def handle_moderation(msg: dict) -> bool:
    """
    Auto-moderates group, supergroup, and channel discussion messages:
    - Auto-deletes links/URLs from non-admin members.
    - Auto-deletes files/documents/APKs from non-admin members.
    - Optionally bans spammers if AUTO_BAN_SPAMMERS is enabled.
    Returns True if the message was deleted/moderated.
    """
    if not config.ENABLE_MODERATION:
        return False

    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type", "")
    if chat_type not in ("group", "supergroup"):
        return False

    from_user = msg.get("from", {})
    user_id = from_user.get("id")
    if not user_id:
        return False

    # Ignore bot itself or chat administrators
    if from_user.get("is_bot") and from_user.get("username") == bot_username:
        return False
    if is_chat_admin(chat_id, user_id):
        return False

    message_id = msg.get("message_id")
    text = msg.get("text", "") or msg.get("caption", "")
    entities = (msg.get("entities") or []) + (msg.get("caption_entities") or [])
    username = from_user.get("username") or from_user.get("first_name") or str(user_id)

    # 1. Detect and delete Links / URLs
    has_link = False
    if config.AUTO_DELETE_LINKS:
        for ent in entities:
            if ent.get("type") in ("url", "text_link"):
                has_link = True
                break
        if not has_link and text:
            if re.search(r"(https?://|t\.me/|www\.)[^\s]+", text, re.IGNORECASE):
                has_link = True

    if has_link:
        logger.info(f"🛡️ [Auto-Moderation] Link detected from non-admin @{username} in {chat_type} {chat_id}. Deleting message {message_id}...")
        deleted = tg.delete_message(chat_id, message_id)
        if config.AUTO_BAN_SPAMMERS:
            logger.info(f"🛡️ [Auto-Moderation] Banning spammer @{username} (ID: {user_id})...")
            tg.ban_chat_member(chat_id, user_id)
        return deleted

    # 2. Detect and delete Files / Documents / Audio / Videos
    has_file = False
    if config.AUTO_DELETE_FILES:
        if any(k in msg for k in ("document", "audio", "video_note", "animation")):
            has_file = True

    if has_file:
        logger.info(f"🛡️ [Auto-Moderation] File/Document detected from non-admin @{username} in {chat_type} {chat_id}. Deleting message {message_id}...")
        deleted = tg.delete_message(chat_id, message_id)
        if config.AUTO_BAN_SPAMMERS:
            logger.info(f"🛡️ [Auto-Moderation] Banning spammer @{username} (ID: {user_id})...")
            tg.ban_chat_member(chat_id, user_id)
        return deleted

    return False


def bot_polling_loop():
    """
    Polls Telegram for incoming user commands and group/channel moderation.
    Ignores channel posts to prevent interfering with channel content.
    """
    logger.info("Telegram Bot Polling started...")
    last_update_id = None

    while running:
        try:
            updates = tg.get_updates(offset=last_update_id, timeout=10)
            for update in updates:
                last_update_id = update["update_id"] + 1

                # Ignore channel posts and edited channel posts
                if "channel_post" in update or "edited_channel_post" in update:
                    continue

                msg = update.get("message")
                if not msg:
                    continue

                chat = msg.get("chat", {})
                chat_type = chat.get("type", "private")

                # If group/supergroup/channel discussion, run auto-moderation
                if chat_type in ("group", "supergroup"):
                    handle_moderation(msg)
                    continue

                # Only respond to user commands in private chats (1-on-1 direct user interaction)
                if chat_type != "private":
                    continue

                chat_id = chat.get("id")
                text = msg.get("text", "")
                user_info = {
                    "username": msg.get("from", {}).get("username") or chat.get("username", ""),
                    "first_name": msg.get("from", {}).get("first_name") or chat.get("first_name", "")
                }
                if chat_id and text:
                    handle_user_command(chat_id, text, user_info=user_info)

        except Exception as e:
            logger.debug(f"Polling loop exception: {e}")
            time.sleep(2)


def main():
    global running, bot_username
    mode_desc = "Big News Only" if config.ONLY_BIG_NEWS else "All Technology News"
    logger.info(f"Starting NewsAI Telegram Bot ({mode_desc})...")

    # Validate bot token
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing! Please configure .env file.")
        print("\n[!] Error: TELEGRAM_BOT_TOKEN is missing in .env")
        print("[!] Please copy .env.example to .env and fill in your TELEGRAM_BOT_TOKEN.\n")
    else:
        me_info = tg.get_me()
        if me_info.get("ok"):
            bot_username = me_info.get("result", {}).get("username", "Unknown")
            logger.info(f"Connected to Telegram Bot: @{bot_username}")
        else:
            logger.warning(f"Could not verify Telegram bot token: {me_info.get('error')}")

    # Verify Telegram channels if configured
    if config.TELEGRAM_CHANNEL_IDS and config.BROADCAST_TO_CHANNEL:
        logger.info(f"Verifying {len(config.TELEGRAM_CHANNEL_IDS)} configured Telegram channel(s)...")
        for ch in config.TELEGRAM_CHANNEL_IDS:
            ch_info = tg.check_channel_access(ch)
            if ch_info.get("ok"):
                title = ch_info.get("title", "")
                c_type = ch_info.get("type", "")
                c_id = ch_info.get("id", "")
                logger.info(f"✅ Connected to Telegram Channel: '{title}' ({c_type}) [ID: {c_id}]")
            else:
                logger.warning(f"⚠️ Channel Warning for '{ch}': {ch_info.get('error')}")

    # Seed baseline news
    seed_existing_news()

    # Start background alert thread
    alert_thread = threading.Thread(target=news_alert_loop, daemon=True, name="NewsAlertWorker")
    alert_thread.start()

    # If bot token is present, run polling loop in main thread
    if config.TELEGRAM_BOT_TOKEN:
        try:
            bot_polling_loop()
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
            running = False
    else:
        try:
            while running:
                time.sleep(1)
        except KeyboardInterrupt:
            running = False

    logger.info("NewsAI Bot stopped gracefully.")


if __name__ == "__main__":
    main()

