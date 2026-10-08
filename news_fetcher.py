import re
import os
import time
import hashlib
import logging
import requests
import urllib.parse
from html import unescape
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict, Optional, Set

import config
from news_sources import (
    TRUSTED_NEWS_SOURCES,
    NEWS_CATEGORY_SOURCES,
    detect_news_category
)

logger = logging.getLogger(__name__)


# =============================================================================
# TEXT / DUPLICATE DETECTION
# =============================================================================

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "up", "about", "into", "over", "after", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "it", "its",
    "this", "that", "these", "those", "if", "not", "new", "more", "now",
    "which", "what", "how", "why", "when", "where", "who", "than", "their",
    "daily", "use", "using", "used", "better", "best"
}


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "fbclid", "gclid", "source", "feature", "feedburner", "rss"
}


def clean_article_url(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""

    try:
        parsed = urllib.parse.urlparse(url)

        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        path = parsed.path.rstrip("/")

        query_tuples = urllib.parse.parse_qsl(
            parsed.query,
            keep_blank_values=False
        )

        filtered_query = [
            (k, v)
            for k, v in query_tuples
            if (
                k.lower() not in _TRACKING_PARAMS
                and not k.lower().startswith("utm_")
            )
        ]

        clean_query = urllib.parse.urlencode(filtered_query)

        if clean_query:
            return f"{netloc}{path}?{clean_query}"

        return f"{netloc}{path}"

    except Exception:
        return url.strip().lower()


def generate_item_id(link: str, title: str, guid: str = "") -> str:
    """
    Generates a deterministic hash independent of source_name so syndicated
    articles or cross-posted news share the same identity.
    """

    clean_url = clean_article_url(link or guid)

    if clean_url:
        return hashlib.sha1(
            clean_url.encode("utf-8", errors="ignore")
        ).hexdigest()

    clean_title = re.sub(
        r"[^\w\s]",
        "",
        (title or "").lower()
    )

    norm_title = " ".join(clean_title.split())

    return hashlib.sha1(
        norm_title.encode("utf-8", errors="ignore")
    ).hexdigest()


_NEWS_VERBS_AND_FILLERS = {
    "says", "said", "announces", "announced", "launches", "launched", "unveils",
    "unveiled", "reveals", "revealed", "introduces", "introduced", "reports",
    "reported", "warns", "warned", "confirms", "confirmed", "new", "update",
    "updates", "latest", "exclusive", "breaking", "alert", "here", "why", "how",
    "what", "when", "after", "amid", "over", "into", "first", "look", "review",
    "top", "best", "more", "now", "could", "would", "will", "can", "may",
    "techcrunch", "verge", "wired", "bleepingcomputer", "thehackernews",
    "hackernews", "reuters", "bloomberg", "cnbc", "cnet", "zdnet", "engadget",
    "arstechnica", "gizmodo", "venturebeat", "securityweek", "edition", "daily"
}


_SYNONYMS = {
    "down": "outage",
    "downtime": "outage",
    "offline": "outage",
    "crashes": "outage",
    "crash": "outage",

    "flaw": "vulnerability",
    "bug": "vulnerability",

    "zero-day": "zeroday",
    "0-day": "zeroday",

    "hacked": "attack",
    "hack": "attack",
    "hacker": "attack",
    "hackers": "attack",
    "breached": "breach",
    "breaches": "breach",
    "attacked": "attack",
    "attackers": "attack",
    "attacks": "attack",

    "exploited": "exploit",
    "exploits": "exploit",
    "exploiting": "exploit",
}


def _extract_core_tokens(title: str) -> Set[str]:
    if not title:
        return set()

    clean = re.sub(r"[^\w\s-]", " ", title.lower())

    tokens = set()

    for w in clean.split():
        w = w.strip("-")

        if len(w) <= 1:
            continue

        if w in _STOP_WORDS:
            continue

        if w in _NEWS_VERBS_AND_FILLERS:
            continue

        w = _SYNONYMS.get(w, w)

        tokens.add(w)

    return tokens


def _title_word_count(title: str) -> int:
    if not title:
        return 0

    return len(
        [
            w
            for w in re.findall(r"\b[\w-]+\b", title.lower())
            if w not in _STOP_WORDS
        ]
    )


def _meaningful_token_overlap(core_a: Set[str], core_b: Set[str]) -> int:
    return len(core_a & core_b)


def _is_likely_duplicate(
    title_a: str,
    core_a: Set[str],
    title_b: str,
    core_b: Set[str],
) -> bool:
    """
    Conservative duplicate detection.

    Important:
    Generic words alone must NOT make two articles duplicates.

    Examples that should NOT become duplicates:
        EV chargers vs MacBook sleep/shutdown

    Strong duplicates should normally share several meaningful tokens.
    """

    if not core_a or not core_b:
        return False

    intersection = core_a & core_b

    if not intersection:
        return False

    union = core_a | core_b

    if not union:
        return False

    inter_count = len(intersection)

    jaccard = inter_count / len(union)

    min_core = min(len(core_a), len(core_b))

    overlap = inter_count / min_core if min_core else 0.0

    word_count_a = _title_word_count(title_a)
    word_count_b = _title_word_count(title_b)

    # -------------------------------------------------------------------------
    # Very short titles:
    # Be extremely conservative.
    # -------------------------------------------------------------------------
    if min_core <= 2:
        return inter_count >= 2 and jaccard >= 0.80

    # -------------------------------------------------------------------------
    # 3 meaningful tokens:
    # Require strong overlap.
    # -------------------------------------------------------------------------
    if min_core == 3:
        return (
            inter_count >= 3
            and overlap >= 0.80
            and jaccard >= 0.60
        )

    # -------------------------------------------------------------------------
    # Normal titles:
    # Strong token overlap OR very high Jaccard similarity.
    # -------------------------------------------------------------------------
    if inter_count >= 4 and overlap >= 0.70:
        return True

    if inter_count >= 3 and overlap >= 0.80 and jaccard >= 0.55:
        return True

    if inter_count >= 4 and jaccard >= 0.55:
        return True

    # -------------------------------------------------------------------------
    # Long titles can share more common context, so require high similarity.
    # -------------------------------------------------------------------------
    if (
        word_count_a >= 8
        and word_count_b >= 8
        and inter_count >= 5
        and jaccard >= 0.60
    ):
        return True

    return False


def deduplicate_items_batch(items: List[Dict]) -> List[Dict]:
    """
    Deduplicates a batch of news items using:

    1. Exact normalized URL matching.
    2. Conservative semantic core-token matching.

    This intentionally avoids the old aggressive rule:
        len(intersection) >= 3 AND overlap >= 50%

    because that caused unrelated titles to be dropped.
    """

    unique_items: List[Dict] = []

    seen_urls = set()
    seen_records: List[Dict] = []

    for item in items:
        link = item.get("link", "")
        title = (item.get("title_en", "") or "").strip()

        norm_u = clean_article_url(link)

        # ---------------------------------------------------------------------
        # Exact URL duplicate
        # ---------------------------------------------------------------------
        if norm_u and norm_u in seen_urls:
            logger.info(
                f"Intra-batch duplicate dropped by URL: '{title}'"
            )
            continue

        core = _extract_core_tokens(title)

        is_dup = False

        if len(core) >= 2:
            for prev in seen_records:
                prev_core = prev["core"]

                if _is_likely_duplicate(
                    title,
                    core,
                    prev["title"],
                    prev_core
                ):
                    logger.info(
                        "Intra-batch duplicate dropped by semantic match: "
                        f"'{title}' matches '{prev['title']}'"
                    )

                    is_dup = True
                    break

        if is_dup:
            continue

        if norm_u:
            seen_urls.add(norm_u)

        if len(core) >= 2:
            seen_records.append(
                {
                    "title": title,
                    "core": core
                }
            )

        unique_items.append(item)

    return unique_items


# =============================================================================
# OPTIONAL DEPENDENCIES
# =============================================================================

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


# =============================================================================
# HTTP
# =============================================================================

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36 NewsAI/3.1"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


_OG_IMAGE_CACHE: Dict[str, str] = {}


def _safe_retry_after(resp: requests.Response, default: int = 5) -> int:
    try:
        value = resp.headers.get("Retry-After")

        if not value:
            return default

        return max(1, min(int(value), 60))

    except Exception:
        return default


def _request_feed(
    feed_url: str,
    source_name: str,
    max_attempts: int = 3,
) -> Optional[bytes]:
    """
    Resilient RSS request.

    Handles:
        - HTTP 200
        - HTTP 429
        - HTTP 5xx
        - connection reset / RemoteDisconnected
        - timeout
    """

    for attempt in range(1, max_attempts + 1):

        try:
            resp = requests.get(
                feed_url,
                headers=DEFAULT_HEADERS,
                timeout=config.HTTP_TIMEOUT,
                allow_redirects=True,
            )

            status = resp.status_code

            # -----------------------------------------------------------------
            # Success
            # -----------------------------------------------------------------
            if status == 200:
                if not resp.content:
                    logger.warning(
                        f"[news] Empty feed response for {source_name}"
                    )
                    return None

                return resp.content

            # -----------------------------------------------------------------
            # Rate limited
            # -----------------------------------------------------------------
            if status == 429:
                retry_after = _safe_retry_after(
                    resp,
                    default=min(5 * attempt, 20)
                )

                logger.warning(
                    f"[news] Feed HTTP 429 for {source_name} "
                    f"(attempt {attempt}/{max_attempts}). "
                    f"Retrying in {retry_after}s..."
                )

                if attempt < max_attempts:
                    time.sleep(retry_after)
                    continue

                return None

            # -----------------------------------------------------------------
            # Forbidden
            # -----------------------------------------------------------------
            if status == 403:
                logger.warning(
                    f"[news] Feed HTTP 403 for {source_name} "
                    f"({feed_url}) - source denied access"
                )

                # Do NOT hammer a source that explicitly denied access.
                return None

            # -----------------------------------------------------------------
            # Other transient HTTP errors
            # -----------------------------------------------------------------
            if status in (500, 502, 503, 504):
                delay = min(2 ** attempt, 10)

                logger.warning(
                    f"[news] Feed HTTP {status} for {source_name} "
                    f"(attempt {attempt}/{max_attempts}). "
                    f"Retrying in {delay}s..."
                )

                if attempt < max_attempts:
                    time.sleep(delay)
                    continue

                return None

            # -----------------------------------------------------------------
            # Other HTTP errors
            # -----------------------------------------------------------------
            logger.warning(
                f"[news] Feed HTTP {status} for {source_name} "
                f"({feed_url})"
            )

            return None

        except requests.exceptions.Timeout as e:
            delay = min(2 ** attempt, 10)

            logger.warning(
                f"[news] Feed timeout for {source_name} "
                f"(attempt {attempt}/{max_attempts}): {e}"
            )

            if attempt < max_attempts:
                time.sleep(delay)
                continue

        except requests.exceptions.ConnectionError as e:
            delay = min(2 ** attempt, 10)

            logger.warning(
                f"[news] Feed connection error for {source_name} "
                f"(attempt {attempt}/{max_attempts}): {e}"
            )

            if attempt < max_attempts:
                time.sleep(delay)
                continue

        except Exception as e:
            logger.warning(
                f"[news] Failed to fetch feed for {source_name}: {e}"
            )
            break

    return None


# =============================================================================
# XML SANITIZATION
# =============================================================================

def _remove_invalid_xml_chars(data: bytes) -> bytes:
    """
    Removes characters forbidden by XML 1.0.

    This is useful when an RSS provider accidentally places control
    characters inside an otherwise usable XML feed.
    """

    if not data:
        return data

    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = data.decode("latin-1", errors="replace")

    # XML 1.0 legal ranges:
    # \x09, \x0A, \x0D, \x20-\uD7FF, \uE000-\uFFFD
    # Supplementary planes are omitted here because Python XML handling
    # can vary by parser/runtime.
    cleaned = []

    for ch in text:
        code = ord(ch)

        if (
            code == 0x09
            or code == 0x0A
            or code == 0x0D
            or 0x20 <= code <= 0xD7FF
            or 0xE000 <= code <= 0xFFFD
        ):
            cleaned.append(ch)

    return "".join(cleaned).encode("utf-8", errors="ignore")


# =============================================================================
# HTML
# =============================================================================

def _clean_html_text(raw_html: str) -> str:
    if not raw_html:
        return ""

    if _HAS_BS4:
        try:
            soup = BeautifulSoup(
                raw_html,
                "html.parser"
            )

            text = soup.get_text(
                separator=" ",
                strip=True
            )

            return unescape(
                re.sub(
                    r"\s+",
                    " ",
                    text
                ).strip()
            )

        except Exception:
            pass

    clean = re.sub(
        r"<[^>]+>",
        " ",
        raw_html
    )

    clean = unescape(clean)

    return re.sub(
        r"\s+",
        " ",
        clean
    ).strip()


# =============================================================================
# OPEN GRAPH IMAGE
# =============================================================================

def extract_og_image(
    article_url: str,
    timeout: int = 3
) -> Optional[str]:

    if not article_url or not article_url.startswith(
        ("http://", "https://")
    ):
        return None

    if article_url in _OG_IMAGE_CACHE:
        return _OG_IMAGE_CACHE[article_url]

    try:
        resp = requests.get(
            article_url,
            headers=DEFAULT_HEADERS,
            timeout=timeout
        )

        if resp.status_code == 200:
            html = resp.text

            match = re.search(
                r'<meta[^>]+property=["\']og:image["\'][^>]+'
                r'content=["\']([^"\']+)["\']',
                html,
                re.IGNORECASE
            )

            if not match:
                match = re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
                    r'property=["\']og:image["\']',
                    html,
                    re.IGNORECASE
                )

            if not match:
                match = re.search(
                    r'<meta[^>]+name=["\']twitter:image["\'][^>]+'
                    r'content=["\']([^"\']+)["\']',
                    html,
                    re.IGNORECASE
                )

            if match:
                img_url = unescape(
                    match.group(1).strip()
                )

                if img_url.startswith(
                    ("http://", "https://")
                ):
                    _OG_IMAGE_CACHE[article_url] = img_url
                    return img_url

    except Exception as e:
        logger.debug(
            f"OpenGraph image fetch failed for "
            f"{article_url}: {e}"
        )

    _OG_IMAGE_CACHE[article_url] = ""

    return None


# =============================================================================
# IMAGE EXTRACTION - FEEDPARSER
# =============================================================================

def extract_image_from_feedparser_entry(
    entry: dict
) -> Optional[str]:

    # 1. media_content
    if "media_content" in entry:
        for m in entry.media_content:
            url = m.get("url")

            if url and url.startswith(
                ("http://", "https://")
            ):
                return url

    # 2. media_thumbnail
    if "media_thumbnail" in entry:
        for m in entry.media_thumbnail:
            url = m.get("url")

            if url and url.startswith(
                ("http://", "https://")
            ):
                return url

    # 3. enclosures
    if "enclosures" in entry:
        for enc in entry.enclosures:
            href = enc.get("href") or enc.get("url")
            enc_type = enc.get("type", "").lower()

            if href and (
                enc_type.startswith("image/")
                or href.lower().endswith(
                    (".jpg", ".png", ".webp", ".jpeg", ".gif")
                )
            ):
                return href

    # 4. summary / description HTML
    for field in ("summary", "description"):
        desc = entry.get(field, "")

        if desc:
            img_match = re.search(
                r'<img[^>]+src=["\']([^"\']+)["\']',
                desc,
                re.IGNORECASE
            )

            if img_match:
                img_url = unescape(
                    img_match.group(1).strip()
                )

                if img_url.startswith(
                    ("http://", "https://")
                ):
                    return img_url

    # 5. content field HTML
    if "content" in entry:
        for c in entry.content:
            c_val = c.get("value", "")

            img_match = re.search(
                r'<img[^>]+src=["\']([^"\']+)["\']',
                c_val,
                re.IGNORECASE
            )

            if img_match:
                img_url = unescape(
                    img_match.group(1).strip()
                )

                if img_url.startswith(
                    ("http://", "https://")
                ):
                    return img_url

    return None


# =============================================================================
# IMAGE EXTRACTION - ELEMENTTREE
# =============================================================================

def extract_image_from_xml_node(item) -> Optional[str]:

    try:
        # media:content
        for tag in (
            "{http://search.yahoo.com/mrss/}content",
            "media:content"
        ):
            media = item.find(tag)

            if media is not None and media.attrib.get("url"):
                return media.attrib.get("url")

        # media:thumbnail
        for tag in (
            "{http://search.yahoo.com/mrss/}thumbnail",
            "media:thumbnail"
        ):
            thumb = item.find(tag)

            if thumb is not None and thumb.attrib.get("url"):
                return thumb.attrib.get("url")

        # enclosure
        enclosure = item.find("enclosure")

        if enclosure is not None and enclosure.attrib.get("url"):
            return enclosure.attrib.get("url")

        # description / content img tag
        for tag in (
            "description",
            "summary",
            "{http://www.w3.org/2005/Atom}summary"
        ):
            desc = item.findtext(tag, "") or ""

            match = re.search(
                r'<img[^>]+src=["\']([^"\']+)["\']',
                desc,
                re.IGNORECASE
            )

            if match:
                return unescape(match.group(1))

    except Exception:
        pass

    return None


# =============================================================================
# XML HELPERS
# =============================================================================

def _xml_find_text(
    item,
    names: List[str]
) -> str:

    for name in names:
        try:
            val = item.findtext(name)

            if val:
                return unescape(
                    str(val).strip()
                )

        except Exception:
            pass

    return ""


# =============================================================================
# RSS / ATOM PARSER
# =============================================================================

def parse_feed_items(
    feed_url: str,
    source_name: str = "News",
    limit: int = 6,
    category: str = "tech"
) -> List[Dict]:
    """
    Fetches and parses RSS/Atom feeds using:

        1. requests
        2. feedparser
        3. sanitized ElementTree fallback

    Feed-specific failures return [] and do not crash the bot.
    """

    raw_content = _request_feed(
        feed_url=feed_url,
        source_name=source_name,
        max_attempts=3
    )

    if not raw_content:
        return []

    # =========================================================================
    # Preferred path: feedparser
    # =========================================================================

    if _HAS_FEEDPARSER:

        try:
            feed = feedparser.parse(raw_content)

            items = []

            for entry in feed.entries[:limit]:

                title = entry.get(
                    "title",
                    ""
                ).strip()

                if not title:
                    continue

                link = entry.get(
                    "link",
                    ""
                )

                guid = (
                    entry.get("id")
                    or entry.get("guid")
                    or link
                    or title
                )

                pub = (
                    entry.get("published", "")
                    or entry.get("updated", "")
                    or ""
                )

                pub = pub[:32]

                desc = (
                    entry.get("summary", "")
                    or entry.get("description", "")
                )

                clean_desc = _clean_html_text(desc)

                # Extract image
                image_url = extract_image_from_feedparser_entry(
                    entry
                )

                # OpenGraph fallback
                if not image_url and link:
                    image_url = extract_og_image(
                        link,
                        timeout=3
                    )

                item_id = generate_item_id(
                    link=link,
                    title=title,
                    guid=guid
                )

                items.append(
                    {
                        "id": item_id,
                        "title_en": title,
                        "summary_en": clean_desc[:500],
                        "source": source_name,
                        "pub": pub,
                        "link": link,
                        "image_url": image_url,
                        "category": category,
                    }
                )

            if items:
                return items

        except Exception as e:
            logger.warning(
                f"[news] feedparser parsing failed "
                f"for {source_name}: {e}"
            )

    # =========================================================================
    # ElementTree fallback
    # =========================================================================

    try:
        root = ET.fromstring(raw_content)

    except Exception as first_error:

        logger.warning(
            f"[news] XML parse failed for {source_name}: "
            f"{first_error}. Trying sanitized XML..."
        )

        try:
            sanitized = _remove_invalid_xml_chars(
                raw_content
            )

            root = ET.fromstring(sanitized)

        except Exception as second_error:

            logger.error(
                f"[news] ElementTree fallback failed "
                f"for {source_name}: {second_error}"
            )

            return []

    try:
        items = []

        channel = root.find("channel")

        raw_items = (
            channel.findall("item")
            if channel is not None
            else []
        )

        # Atom
        if not raw_items:
            raw_items = root.findall(
                "{http://www.w3.org/2005/Atom}entry"
            )

        for item in raw_items[:limit]:

            title = _xml_find_text(
                item,
                [
                    "title",
                    "{http://www.w3.org/2005/Atom}title"
                ]
            )

            if not title:
                continue

            link = item.findtext("link") or ""

            if not link:
                atom_link = item.find(
                    "{http://www.w3.org/2005/Atom}link"
                )

                if atom_link is not None:
                    link = atom_link.attrib.get(
                        "href",
                        ""
                    )

            guid = (
                item.findtext("guid")
                or item.findtext("id")
                or link
                or title
            )

            pub = (
                item.findtext("pubDate")
                or item.findtext("published")
                or item.findtext("updated")
                or ""
            )[:32]

            desc = _xml_find_text(
                item,
                [
                    "description",
                    "summary",
                    "{http://www.w3.org/2005/Atom}summary"
                ]
            )

            image_url = extract_image_from_xml_node(
                item
            )

            if not image_url and link:
                image_url = extract_og_image(
                    link,
                    timeout=3
                )

            clean_desc = _clean_html_text(desc)

            item_id = generate_item_id(
                link=link,
                title=title,
                guid=guid
            )

            items.append(
                {
                    "id": item_id,
                    "title_en": title,
                    "summary_en": clean_desc[:500],
                    "source": source_name,
                    "pub": pub,
                    "link": link,
                    "image_url": image_url,
                    "category": category,
                }
            )

        return items

    except Exception as e:

        logger.error(
            f"[news] ElementTree item extraction failed "
            f"for {source_name}: {e}"
        )

        return []


# =============================================================================
# TRUSTED SOURCES
# =============================================================================

def fetch_trusted_news_by_category(
    category: str = "tech",
    max_per_source: int = 3
) -> List[Dict]:
    """
    Fetches news from trusted RSS sources configured for category.
    """

    source_keys = NEWS_CATEGORY_SOURCES.get(
        category,
        [
            "techcrunch",
            "arstechnica",
            "theverge"
        ]
    )

    all_items = []

    for key in source_keys:

        src_info = TRUSTED_NEWS_SOURCES.get(key)

        if not src_info:
            continue

        rss_url = src_info.get("rss")
        name = src_info.get("name", key)

        if not rss_url:
            continue

        try:
            items = parse_feed_items(
                rss_url,
                source_name=name,
                limit=max_per_source,
                category=category
            )

            all_items.extend(items)

        except Exception as e:
            logger.warning(
                f"[news] Source processing failed for "
                f"{name}: {e}"
            )

            continue

    return all_items


# =============================================================================
# NEWS API
# =============================================================================

def fetch_news_from_api(
    category: str = "tech",
    limit: int = 6
) -> List[Dict]:

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

    q = query_map.get(
        category,
        category
    )

    url = (
        "https://newsapi.org/v2/everything"
        f"?q={q}"
        "&sortBy=publishedAt"
        f"&pageSize={limit}"
        f"&apiKey={config.NEWS_API_KEY}"
    )

    try:
        resp = requests.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=config.HTTP_TIMEOUT
        )

    except Exception as e:
        logger.warning(
            f"NewsAPI request failed: {e}"
        )
        raise

    if resp.status_code != 200:

        logger.warning(
            f"NewsAPI error {resp.status_code}: {resp.text}"
        )

        raise RuntimeError(
            f"NewsAPI returned status {resp.status_code}"
        )

    data = resp.json()

    if data.get("status") != "ok":

        raise RuntimeError(
            f"NewsAPI error: "
            f"{data.get('message', 'Unknown')}"
        )

    articles = data.get(
        "articles",
        []
    )

    items = []

    for art in articles:

        title = art.get(
            "title",
            ""
        ).strip()

        if not title or "[Removed]" in title:
            continue

        source_name = (
            art.get("source", {})
            .get("name", "NewsAPI")
        )

        link = art.get(
            "url",
            ""
        )

        pub = (
            art.get("publishedAt", "")
        )[:19].replace(
            "T",
            " "
        )

        desc = (
            art.get("description", "")
            or art.get("content", "")
            or ""
        )

        clean_desc = _clean_html_text(desc)

        image_url = art.get(
            "urlToImage"
        )

        item_id = generate_item_id(
            link=link,
            title=title
        )

        items.append(
            {
                "id": item_id,
                "title_en": title,
                "summary_en": clean_desc[:500],
                "source": source_name,
                "pub": pub,
                "link": link,
                "image_url": image_url,
                "category": category,
            }
        )

    return items


# =============================================================================
# LATEST NEWS
# =============================================================================

_NEWS_API_COOLDOWN_UNTIL = 0.0


def fetch_latest_news(
    category: str = "tech",
    max_items: int = 5,
    require_image: bool = None
) -> List[Dict]:
    """
    1. Primary:
       Trusted RSS feeds.

    2. Fallback:
       NewsAPI if RSS produces zero items.

    3. Dedup:
       Conservative multi-factor semantic deduplication.

    4. Image:
       Optional photo-card filtering.
    """

    category = detect_news_category(
        category
    )

    if require_image is None:
        require_image = config.REQUIRE_PHOTO_CARD

    # =========================================================================
    # Primary RSS
    # =========================================================================

    logger.info(
        f"Fetching {category} news from trusted RSS sources..."
    )

    items = fetch_trusted_news_by_category(
        category=category,
        max_per_source=3
    )

    # =========================================================================
    # NewsAPI fallback
    # =========================================================================

    if not items and config.NEWS_API_KEY:

        try:
            logger.info(
                f"RSS empty; fetching {category} "
                f"news via NewsAPI fallback..."
            )

            items = fetch_news_from_api(
                category=category,
                limit=max_items * 2
            )

        except Exception as e:
            logger.warning(
                f"NewsAPI fallback failed: {e}"
            )

    # =========================================================================
    # Deduplication
    # =========================================================================

    items = deduplicate_items_batch(
        items
    )

    # =========================================================================
    # Image requirement
    # =========================================================================

    if require_image:

        items_with_image = [
            item
            for item in items
            if (
                item.get("image_url")
                and item.get("image_url").startswith(
                    ("http://", "https://")
                )
            )
        ]

        if items_with_image:
            return items_with_image[:max_items]

        logger.info(
            f"No articles with valid image found "
            f"in primary pool for {category}."
        )

        return []

    return items[:max_items]