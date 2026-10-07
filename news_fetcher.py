import re
import os
import time
import hashlib
import logging
import requests
from html import unescape
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict, Optional


import config
from news_sources import (
    TRUSTED_NEWS_SOURCES,
    NEWS_CATEGORY_SOURCES,
    detect_news_category
)

logger = logging.getLogger(__name__)

# Check if feedparser and BeautifulSoup are available
try:
    import feedparser
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 NewsAI/3.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_OG_IMAGE_CACHE: Dict[str, str] = {}


def _clean_html_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    if _HAS_BS4:
        try:
            soup = BeautifulSoup(raw_html, "html.parser")
            text = soup.get_text(separator=" ", strip=True)
            return unescape(re.sub(r"\s+", " ", text).strip())
        except Exception:
            pass
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    clean = unescape(clean)
    return re.sub(r"\s+", " ", clean).strip()


def extract_og_image(article_url: str, timeout: int = 3) -> Optional[str]:
    """
    Attempts to fetch Open Graph (og:image) from the article webpage.
    Results are cached in memory.
    """
    if not article_url or not article_url.startswith(("http://", "https://")):
        return None
    if article_url in _OG_IMAGE_CACHE:
        return _OG_IMAGE_CACHE[article_url]

    try:
        resp = requests.get(article_url, headers=DEFAULT_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            html = resp.text
            # Fast regex for og:image
            match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if not match:
                match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.IGNORECASE)
            if not match:
                match = re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)

            if match:
                img_url = unescape(match.group(1).strip())
                if img_url.startswith(("http://", "https://")):
                    _OG_IMAGE_CACHE[article_url] = img_url
                    return img_url
    except Exception as e:
        logger.debug(f"OpenGraph image fetch failed for {article_url}: {e}")

    _OG_IMAGE_CACHE[article_url] = ""
    return None


def extract_image_from_feedparser_entry(entry: dict) -> Optional[str]:
    """
    Multi-tier image extraction from feedparser entry.
    """
    # 1. media_content
    if "media_content" in entry:
        for m in entry.media_content:
            url = m.get("url")
            if url and url.startswith(("http://", "https://")):
                return url

    # 2. media_thumbnail
    if "media_thumbnail" in entry:
        for m in entry.media_thumbnail:
            url = m.get("url")
            if url and url.startswith(("http://", "https://")):
                return url

    # 3. enclosures
    if "enclosures" in entry:
        for enc in entry.enclosures:
            href = enc.get("href") or enc.get("url")
            enc_type = enc.get("type", "").lower()
            if href and (enc_type.startswith("image/") or href.lower().endswith((".jpg", ".png", ".webp", ".jpeg", ".gif"))):
                return href

    # 4. summary / description HTML
    for field in ("summary", "description"):
        desc = entry.get(field, "")
        if desc:
            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc, re.IGNORECASE)
            if img_match:
                img_url = unescape(img_match.group(1).strip())
                if img_url.startswith(("http://", "https://")):
                    return img_url

    # 5. content field HTML
    if "content" in entry:
        for c in entry.content:
            c_val = c.get("value", "")
            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', c_val, re.IGNORECASE)
            if img_match:
                img_url = unescape(img_match.group(1).strip())
                if img_url.startswith(("http://", "https://")):
                    return img_url

    return None


def extract_image_from_xml_node(item) -> Optional[str]:
    """
    Extracts image URL from ElementTree XML item.
    """
    try:
        # media:content
        for tag in ('{http://search.yahoo.com/mrss/}content', 'media:content'):
            media = item.find(tag)
            if media is not None and media.attrib.get('url'):
                return media.attrib.get('url')

        # media:thumbnail
        for tag in ('{http://search.yahoo.com/mrss/}thumbnail', 'media:thumbnail'):
            thumb = item.find(tag)
            if thumb is not None and thumb.attrib.get('url'):
                return thumb.attrib.get('url')

        # enclosure
        enclosure = item.find('enclosure')
        if enclosure is not None and enclosure.attrib.get('url'):
            return enclosure.attrib.get('url')

        # description / content img tag
        for tag in ('description', 'summary', '{http://www.w3.org/2005/Atom}summary'):
            desc = item.findtext(tag, '') or ''
            match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc, re.IGNORECASE)
            if match:
                return unescape(match.group(1))
    except Exception:
        pass
    return None


def _xml_find_text(item, names: List[str]) -> str:
    for name in names:
        try:
            val = item.findtext(name)
            if val:
                return unescape(str(val).strip())
        except Exception:
            pass
    return ""


def parse_feed_items(feed_url: str, source_name: str = "News", limit: int = 6, category: str = "tech") -> List[Dict]:
    """
    Fetches and parses RSS/Atom feeds using requests + feedparser with ElementTree fallback.
    """
    raw_content = None
    try:
        resp = requests.get(feed_url, headers=DEFAULT_HEADERS, timeout=config.HTTP_TIMEOUT)
        if resp.status_code == 200:
            raw_content = resp.content
        else:
            logger.warning(f"[news] Feed HTTP {resp.status_code} for {source_name} ({feed_url})")
    except Exception as e:
        logger.warning(f"[news] Failed to fetch feed for {source_name}: {e}")

    # ── Preferred path: feedparser ───────────────────────────────────────────
    if _HAS_FEEDPARSER and raw_content:
        try:
            feed = feedparser.parse(raw_content)
            items = []
            for entry in feed.entries[:limit]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                link = entry.get("link", "")
                guid = entry.get("id") or entry.get("guid") or link or title
                pub = entry.get("published", "") or entry.get("updated", "") or ""
                pub = pub[:32]
                desc = entry.get("summary", "") or entry.get("description", "")
                clean_desc = _clean_html_text(desc)

                # Extract image
                image_url = extract_image_from_feedparser_entry(entry)

                # If still no image and link exists, try fast OpenGraph lookup
                if not image_url and link:
                    image_url = extract_og_image(link, timeout=3)

                item_id = hashlib.sha1(f"{source_name}|{guid}|{title}".encode("utf-8", errors="ignore")).hexdigest()
                items.append({
                    "id": item_id,
                    "title_en": title,
                    "summary_en": clean_desc[:500],
                    "source": source_name,
                    "pub": pub,
                    "link": link,
                    "image_url": image_url,
                    "category": category,
                })
            if items:
                return items
        except Exception as e:
            logger.warning(f"[news] feedparser parsing failed for {source_name}: {e}")

    # ── Fallback: ElementTree method ─────────────────────────────────────────
    if raw_content:
        try:
            root = ET.fromstring(raw_content)
            items = []
            channel = root.find("channel")
            raw_items = channel.findall("item") if channel is not None else []

            if not raw_items:
                raw_items = root.findall("{http://www.w3.org/2005/Atom}entry")

            for item in raw_items[:limit]:
                title = _xml_find_text(item, ["title", "{http://www.w3.org/2005/Atom}title"])
                link = item.findtext("link") or ""
                if not link:
                    atom_link = item.find("{http://www.w3.org/2005/Atom}link")
                    if atom_link is not None:
                        link = atom_link.attrib.get("href", "")
                guid = item.findtext("guid") or item.findtext("id") or link or title
                pub = (item.findtext("pubDate") or item.findtext("published") or item.findtext("updated") or "")[:32]
                desc = _xml_find_text(item, ["description", "summary", "{http://www.w3.org/2005/Atom}summary"])
                image_url = extract_image_from_xml_node(item)
                if not image_url and link:
                    image_url = extract_og_image(link, timeout=3)
                clean_desc = _clean_html_text(desc)

                item_id = hashlib.sha1(f"{source_name}|{guid}|{title}".encode("utf-8", errors="ignore")).hexdigest()
                if title:
                    items.append({
                        "id": item_id,
                        "title_en": title,
                        "summary_en": clean_desc[:500],
                        "source": source_name,
                        "pub": pub,
                        "link": link,
                        "image_url": image_url,
                        "category": category,
                    })
            return items
        except Exception as e:
            logger.error(f"[news] ElementTree fallback failed for {source_name}: {e}")

    return []


def fetch_trusted_news_by_category(category: str = "tech", max_per_source: int = 3) -> List[Dict]:
    """
    Fetches news from trusted RSS sources configured for the given category.
    """
    source_keys = NEWS_CATEGORY_SOURCES.get(category, ["techcrunch", "arstechnica", "theverge"])
    all_items = []

    for key in source_keys:
        src_info = TRUSTED_NEWS_SOURCES.get(key)
        if not src_info:
            continue
        rss_url = src_info.get("rss")
        name = src_info.get("name", key)
        if not rss_url:
            continue

        items = parse_feed_items(rss_url, source_name=name, limit=max_per_source, category=category)
        all_items.extend(items)

    return all_items


def fetch_news_from_api(category: str = "tech", limit: int = 6) -> List[Dict]:
    """
    Fetches news using NewsAPI (if NEWS_API_KEY is configured).
    """
    if not config.NEWS_API_KEY:
        return []

    query_map = {
        "tech": "technology",
        "ai": "artificial intelligence OR chatgpt OR openai OR gemini",
        "security": "cybersecurity OR hacker OR malware OR ransomware",
        "crypto": "crypto OR bitcoin OR ethereum",
        "forex": "forex OR currency OR stock market",
        "business": "business OR finance",
        "auto": "electric vehicles OR tesla OR automotive",
        "usa": "usa news",
        "world": "world news",
    }
    q = query_map.get(category, category)

    url = f"https://newsapi.org/v2/everything?q={q}&sortBy=publishedAt&pageSize={limit}&apiKey={config.NEWS_API_KEY}"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=config.HTTP_TIMEOUT)

    if resp.status_code != 200:
        logger.warning(f"NewsAPI error {resp.status_code}: {resp.text}")
        raise RuntimeError(f"NewsAPI returned status {resp.status_code}")

    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"NewsAPI error: {data.get('message', 'Unknown')}")

    articles = data.get("articles", [])
    items = []
    for art in articles:
        title = art.get("title", "").strip()
        if not title or "[Removed]" in title:
            continue
        source_name = art.get("source", {}).get("name", "NewsAPI")
        link = art.get("url", "")
        pub = art.get("publishedAt", "")[:19].replace("T", " ")
        desc = art.get("description", "") or art.get("content", "") or ""
        clean_desc = _clean_html_text(desc)
        image_url = art.get("urlToImage")
        item_id = hashlib.sha1(f"{source_name}|{link}|{title}".encode("utf-8", errors="ignore")).hexdigest()

        items.append({
            "id": item_id,
            "title_en": title,
            "summary_en": clean_desc[:500],
            "source": source_name,
            "pub": pub,
            "link": link,
            "image_url": image_url,
            "category": category,
        })
    return items


_NEWS_API_COOLDOWN_UNTIL = 0.0


def fetch_latest_news(category: str = "tech", max_items: int = 5, require_image: bool = None) -> List[Dict]:
    """
    Auto-failover orchestrator:
    1. Attempts NewsAPI if API key is present and not on rate-limit cooldown.
    2. If key fails, is rate-limited, or is missing, automatically switches to trusted RSS feeds.
    3. Filters for articles with images if require_image / REQUIRE_PHOTO_CARD is True.
    """
    global _NEWS_API_COOLDOWN_UNTIL
    category = detect_news_category(category)
    if require_image is None:
        require_image = config.REQUIRE_PHOTO_CARD

    items = []
    now = time.time()

    if config.NEWS_API_KEY and now >= _NEWS_API_COOLDOWN_UNTIL:
        try:
            logger.info(f"Attempting to fetch {category} news via NewsAPI...")
            api_items = fetch_news_from_api(category=category, limit=max_items * 2)
            if api_items:
                items = api_items
        except Exception as e:
            # Put NewsAPI on cooldown for 30 minutes to avoid spamming a rate-limited key
            _NEWS_API_COOLDOWN_UNTIL = now + 1800
            logger.warning(f"NewsAPI unavailable ({e}). Switched to trusted RSS feeds fallback (cooldown: 30m).")

    if not items:
        # RSS Fallback
        logger.info(f"Fetching {category} news from trusted RSS sources...")
        items = fetch_trusted_news_by_category(category=category, max_per_source=3)

    # Filter out articles without image if photo card is strictly required
    if require_image:
        items_with_image = [
            item for item in items
            if item.get("image_url") and item.get("image_url").startswith(("http://", "https://"))
        ]
        if items_with_image:
            return items_with_image[:max_items]
        logger.info(f"No articles with valid image found in primary pool for {category}.")
        return []

    return items[:max_items]


