import sys
import logging
import time
from typing import List

# Ensure UTF-8 stdout on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import config
from news_sources import TRUSTED_NEWS_SOURCES, NEWS_CATEGORY_SOURCES, CATEGORY_ICONS_AND_TITLES
from news_fetcher import fetch_latest_news, parse_feed_items
from formatter import format_news_card, heuristic_is_big_news, translate_text_google
from telegram_client import TelegramClient

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def test_rss_feeds():
    print("\n" + "=" * 60)
    print("📡 [1/4] Testing Trusted RSS Feeds Connectivity")
    print("=" * 60)

    total = len(TRUSTED_NEWS_SOURCES)
    success = 0
    with_images = 0

    for key, info in TRUSTED_NEWS_SOURCES.items():
        name = info["name"]
        rss_url = info["rss"]
        print(f"Testing {name:25} -> ", end="", flush=True)

        try:
            items = parse_feed_items(rss_url, source_name=name, limit=2)
            if items:
                img_count = sum(1 for it in items if it.get("image_url"))
                print(f"✅ OK ({len(items)} items, {img_count} with image)")
                success += 1
                if img_count > 0:
                    with_images += 1
            else:
                print("⚠️ No items returned")
        except Exception as e:
            print(f"❌ Error: {e}")

    print("-" * 60)
    print(f"Result: {success}/{total} feeds reachable | {with_images}/{total} sources providing images.")


def test_gemini_and_translator():
    print("\n" + "=" * 60)
    print("🤖 [2/4] Testing AI & Translation Engine")
    print("=" * 60)

    sample_text = "Critical security vulnerability discovered in popular cloud infrastructure allowing remote code execution."
    print(f"Original Text: {sample_text}\n")

    # Test Google Translate
    print("Testing Google Translate (EN -> KM)...")
    km_trans = translate_text_google(sample_text, "km")
    print(f"Translated Khmer: {km_trans}\n")

    # Test Gemini AI
    if config.GEMINI_API_KEY:
        print(f"Testing Gemini AI Key with model '{config.GEMINI_MODEL}'...")
        sample_item = {
            "title_en": "Critical Zero-Day Vulnerability Found in Linux Kernel",
            "summary_en": "Security researchers have disclosed a severe remote code execution vulnerability impacting major enterprise Linux systems.",
            "source": "The Hacker News",
            "link": "https://thehackernews.com/",
            "category": "security",
            "pub": "2026-08-24"
        }
        card = format_news_card(sample_item, translate_to_khmer=True)
        if card:
            print("✅ Gemini AI Card Generated Successfully:")
            print(card)
        else:
            print("⚠️ Gemini AI did not return a card.")
    else:
        print("ℹ️ GEMINI_API_KEY is not configured in .env (Using Google Translate fallback).")


def test_big_news_evaluation():
    print("\n" + "=" * 60)
    print("🔥 [3/4] Testing Big News Filtering & Khmer Card Formatting")
    print(f"Only Big News Mode: {config.ONLY_BIG_NEWS}")
    print(f"Require Photo Card: {config.REQUIRE_PHOTO_CARD}")
    print("=" * 60)

    test_categories = ["security", "ai", "tech", "crypto"]

    for cat in test_categories:
        print(f"\n🔍 Category: [{cat.upper()}]")
        items = fetch_latest_news(category=cat, max_items=2, require_image=config.REQUIRE_PHOTO_CARD)
        if not items:
            print("  ⚠️ No items found matching image criteria.")
            continue

        for i, item in enumerate(items, 1):
            title = item.get("title_en", "")
            img = item.get("image_url")
            print(f"\n  Article #{i}: {title}")
            print(f"  Source: {item.get('source')} | Image: {'✅ Yes' if img else '❌ No'}")

            card = format_news_card(item, translate_to_khmer=True)
            if card:
                print("  🚨 Status: ✅ APPROVED AS BIG NEWS!")
                print("  --- Preview ---")
                for line in card.splitlines()[:5]:
                    print(f"    {line}")
                if len(card.splitlines()) > 5:
                    print("    ...")
            else:
                print("  ℹ️ Status: ❌ Filtered out (not major/breaking news)")


def test_telegram_bot():
    print("\n" + "=" * 60)
    print("📬 [4/4] Testing Telegram Bot Connectivity (Public Bot Mode)")
    print("=" * 60)

    tg = TelegramClient()
    if not tg.is_configured():
        print("⚠️ TELEGRAM_BOT_TOKEN is not configured in .env.")
        return

    me = tg.get_me()
    if me.get("ok"):
        bot_info = me.get("result", {})
        username = bot_info.get("username")
        first_name = bot_info.get("first_name")
        print(f"✅ Bot Verified: @{username} ({first_name})")
        print(f"🌐 Public Bot Link: https://t.me/{username}")
        print("💡 Mode: Public (1-on-1 Direct Chat & Subscriber Alerts)")
        print("   Users can start the bot directly without any group ID.")
    else:
        print(f"❌ Telegram Bot Error: {me.get('error')}")

    # Check Channel Configuration
    if config.TELEGRAM_CHANNEL_IDS:
        print(f"\n📢 Configured Telegram Channel(s): {config.TELEGRAM_CHANNEL_IDS}")
        for ch in config.TELEGRAM_CHANNEL_IDS:
            ch_status = tg.check_channel_access(ch)
            if ch_status.get("ok"):
                print(f"  ✅ Channel Reachable: '{ch_status.get('title')}' (Type: {ch_status.get('type')}) [ID: {ch_status.get('id')}]")
            else:
                print(f"  ❌ Channel Access Error for '{ch}': {ch_status.get('error')}")
    else:
        print("\nℹ️ No Telegram Channels configured in TELEGRAM_CHANNEL_IDS.")

    # Channel test send: python test_news.py --channel [optional_channel_id]
    if "--channel" in sys.argv or "--send-channel" in sys.argv:
        flag = "--channel" if "--channel" in sys.argv else "--send-channel"
        idx = sys.argv.index(flag)
        custom_ch = None
        if len(sys.argv) > idx + 1 and not sys.argv[idx + 1].startswith("-"):
            custom_ch = sys.argv[idx + 1]

        target_channels = [custom_ch] if custom_ch else config.TELEGRAM_CHANNEL_IDS
        if not target_channels:
            print("⚠️ No channel specified. Usage: python test_news.py --channel <@YourChannel or -100xxxxxxxxxx>")
        else:
            print(f"\n🚀 Sending Live News Card Test to Channel(s): {target_channels}...")
            # Fetch a sample article
            items = fetch_latest_news(category="tech", max_items=5, require_image=True)
            if not items:
                items = fetch_latest_news(category="tech", max_items=5, require_image=False)

            if items:
                sample = items[0]
                card = format_news_card(sample, translate_to_khmer=config.TRANSLATE_TO_KHMER)
                img = sample.get("image_url")
                markup = tg.build_read_more_keyboard(sample.get("link", "")) if config.CHANNEL_ENABLE_BUTTONS else None

                for ch in target_channels:
                    print(f"  -> Posting to {ch}...")
                    if img and config.SEND_PHOTO:
                        ok = tg.send_photo(ch, img, card, fallback_to_text=True, reply_markup=markup)
                    else:
                        ok = tg.send_message(ch, card, reply_markup=markup)

                    if ok:
                        print(f"  ✅ Successfully posted sample Photo Card to {ch}!")
                    else:
                        print(f"  ❌ Failed to post to {ch}: {tg.last_error_description}")
            else:
                print("  ⚠️ Could not fetch any news articles to test post.")

    # Optional test send if user passes a specific chat_id: python test_news.py --send <chat_id>
    if "--send" in sys.argv:
        send_idx = sys.argv.index("--send")
        if len(sys.argv) > send_idx + 1 and not sys.argv[send_idx + 1].startswith("-"):
            target_chat_id = sys.argv[send_idx + 1]
            print(f"Sending test message to {target_chat_id}...")
            sent = tg.send_message(
                target_chat_id,
                "🤖 <b>NewsAI Bot Diagnostic Test</b>\n\n✅ ប្រព័ន្ធដំណើរការបានត្រឹមត្រូវជាលក្ខណៈ Public Bot!",
                parse_mode="HTML"
            )
            if sent:
                print("✅ Test message successfully delivered to Telegram!")
            else:
                print(f"❌ Failed to deliver test message to Telegram: {tg.last_error_description}")
        else:
            print("ℹ️ To send a real test message, provide your Telegram User ID: python test_news.py --send <YOUR_USER_ID>")


def run_all_tests():
    print("=" * 60)
    print("🚀 NewsAI System Diagnostics & Integration Tests")
    print("=" * 60)
    test_rss_feeds()
    test_gemini_and_translator()
    test_big_news_evaluation()
    test_telegram_bot()
    print("\n" + "=" * 60)
    print("✅ All diagnostic checks completed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()

