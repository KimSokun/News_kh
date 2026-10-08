import re
import json
import os
import time
import logging
import threading
from pathlib import Path
from typing import Set, List, Dict, Any, Union

logger = logging.getLogger(__name__)


import urllib.parse

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "up", "about", "into", "over", "after", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "it", "its",
    "this", "that", "these", "those", "if", "not", "new", "more", "now"
}

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "fbclid", "gclid", "source", "feature", "feedburner", "rss"
}


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


class NewsSeenTracker:
    def __init__(self, filepath: str, max_items: int = 3000):
        self.filepath = filepath
        self.max_items = max_items
        self._lock = threading.RLock()
        self._seen_ids: Set[str] = set()
        self._seen_titles: Set[str] = set()
        self._seen_urls: Set[str] = set()
        self._history: List[Dict[str, Any]] = []
        self.load()

    def _normalize_title(self, title: str) -> str:
        if not title:
            return ""
        clean = re.sub(r"[^\w\s]", "", title.lower())
        return " ".join(clean.split())

    def _extract_core_tokens(self, title: str) -> Set[str]:
        if not title:
            return set()
        clean = re.sub(r"[^\w\s-]", " ", title.lower())
        tokens = set()
        for w in clean.split():
            w = w.strip("-")
            if len(w) <= 1 or w in _STOP_WORDS or w in _NEWS_VERBS_AND_FILLERS:
                continue
            w = _SYNONYMS.get(w, w)
            tokens.add(w)
        return tokens

    def _tokenize_title(self, title: str) -> Set[str]:
        return self._extract_core_tokens(title)

    def _normalize_url(self, url: str) -> str:
        if not url or not url.startswith(("http://", "https://")):
            return ""
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            path = parsed.path.rstrip("/")

            # Clean tracking query parameters
            query_tuples = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
            filtered_query = [
                (k, v) for k, v in query_tuples
                if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
            ]
            clean_query = urllib.parse.urlencode(filtered_query)

            if clean_query:
                return f"{netloc}{path}?{clean_query}"
            return f"{netloc}{path}"
        except Exception:
            return url.strip().lower()

    def _is_title_duplicate(self, title: str) -> bool:
        """
        Detects if a title refers to the same news event using multi-factor semantic matching:
        1. Core semantic entity overlap (>= 3 core tokens & >= 50% overlap of smaller title).
        2. Significant core Jaccard similarity (>= 0.38 with 2+ tokens).
        3. High containment (>= 4 core tokens & >= 70% overlap).
        """
        core_tokens = self._extract_core_tokens(title)
        if len(core_tokens) < 2:
            return False

        # Scan recent history in reverse (last 500 items)
        for item in reversed(self._history[-500:]):
            if not isinstance(item, dict):
                continue
            hist_title = item.get("title", "")
            if not hist_title:
                continue
            hist_core = self._extract_core_tokens(hist_title)
            if len(hist_core) < 2:
                continue

            intersection = core_tokens & hist_core
            if not intersection:
                continue

            union = core_tokens | hist_core
            jaccard = len(intersection) / len(union) if union else 0.0
            overlap = len(intersection) / min(len(core_tokens), len(hist_core))

            # Case A: 3+ core tokens match and at least 50% overlap
            if len(intersection) >= 3 and overlap >= 0.50:
                logger.info(f"Duplicate news detected by core overlap ({len(intersection)} tokens, {overlap:.0%}): '{title}' matches '{hist_title}'")
                return True

            # Case B: Significant core Jaccard similarity (>= 0.38 with 2+ tokens)
            if len(intersection) >= 2 and jaccard >= 0.38:
                logger.info(f"Duplicate news detected by Jaccard similarity ({jaccard:.0%}): '{title}' matches '{hist_title}'")
                return True

            # Case C: High containment (4+ tokens and 70%+ overlap)
            if len(intersection) >= 4 and overlap >= 0.70:
                logger.info(f"Duplicate news detected by containment ({overlap:.0%}): '{title}' matches '{hist_title}'")
                return True

        return False

    def load(self):
        with self._lock:
            if not os.path.exists(self.filepath) or os.path.getsize(self.filepath) == 0:
                self._seen_ids = set()
                self._seen_titles = set()
                self._seen_urls = set()
                self._history = []
                return

            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._history = [
                            item if isinstance(item, dict) else {"id": str(item), "timestamp": int(time.time())}
                            for item in data
                        ]
                    elif isinstance(data, dict):
                        raw_hist = data.get("history", [])
                        self._history = [
                            h if isinstance(h, dict) else {"id": str(h), "timestamp": int(time.time())}
                            for h in raw_hist
                        ]
                    else:
                        self._history = []

                    self._seen_ids = set()
                    self._seen_titles = set()
                    self._seen_urls = set()
                    for h in self._history:
                        if isinstance(h, dict):
                            if h.get("id"):
                                self._seen_ids.add(h["id"])
                            t = h.get("title")
                            if t:
                                norm = self._normalize_title(t)
                                if norm:
                                    self._seen_titles.add(norm)
                            u = h.get("url") or h.get("link")
                            if u:
                                norm_u = self._normalize_url(u)
                                if norm_u:
                                    self._seen_urls.add(norm_u)
                        elif isinstance(h, str):
                            self._seen_ids.add(h)

            except Exception as e:
                logger.warning(f"Error loading seen news from {self.filepath}, starting fresh: {e}")
                self._seen_ids = set()
                self._seen_titles = set()
                self._seen_urls = set()
                self._history = []

    def is_seen(self, item_id: str, title: str = "", url: str = "") -> bool:
        """
        Returns True if the article has already been seen using 4-layer deduplication:
        1. Exact ID match
        2. Normalized URL match (cleans tracking parameters)
        3. Exact normalized title match
        4. Jaccard token similarity (prevents double posting same news across different feeds)
        """
        with self._lock:
            # 1. ID check
            if item_id and item_id in self._seen_ids:
                return True

            # 2. URL check
            if url:
                norm_u = self._normalize_url(url)
                if norm_u and norm_u in self._seen_urls:
                    return True

            # 3. Exact normalized title check
            if title:
                norm_t = self._normalize_title(title)
                if norm_t and norm_t in self._seen_titles:
                    return True

                # 4. Fuzzy / Jaccard title similarity check
                if self._is_title_duplicate(title):
                    return True

            return False

    def has_seen(self, item_id: str, title: str = "", url: str = "") -> bool:
        return self.is_seen(item_id, title=title, url=url)

    def mark_seen(self, item_id: str, title: str = "", source: str = "", url: str = "") -> bool:
        if not item_id and not title and not url:
            return False

        norm_t = self._normalize_title(title)
        norm_u = self._normalize_url(url)

        with self._lock:
            if item_id:
                self._seen_ids.add(item_id)
            if norm_t:
                self._seen_titles.add(norm_t)
            if norm_u:
                self._seen_urls.add(norm_u)

            self._history.append({
                "id": item_id or "",
                "title": title or "",
                "source": source or "",
                "url": url or "",
                "timestamp": int(time.time())
            })
            self._prune()
            self.save()
            return True

    def mark_many(self, items: list) -> int:
        if not items:
            return 0
        added_count = 0
        with self._lock:
            changed = False
            now = int(time.time())
            for item in items:
                item_id = item.get("id") if isinstance(item, dict) else str(item)
                title = item.get("title_en", "") if isinstance(item, dict) else ""
                source = item.get("source", "") if isinstance(item, dict) else ""
                url = item.get("link", "") or item.get("url", "") if isinstance(item, dict) else ""

                if not self.is_seen(item_id, title=title, url=url):
                    norm_t = self._normalize_title(title)
                    norm_u = self._normalize_url(url)
                    if item_id:
                        self._seen_ids.add(item_id)
                    if norm_t:
                        self._seen_titles.add(norm_t)
                    if norm_u:
                        self._seen_urls.add(norm_u)

                    self._history.append({
                        "id": item_id,
                        "title": title,
                        "source": source,
                        "url": url,
                        "timestamp": now
                    })
                    changed = True
                    added_count += 1
            if changed:
                self._prune()
                self.save()
        return added_count

    def _prune(self):
        # Must be called within self._lock
        if len(self._history) > self.max_items:
            self._history = self._history[-self.max_items:]
            self._seen_ids = {
                item.get("id") if isinstance(item, dict) else str(item)
                for item in self._history
                if item
            }
            self._seen_titles = {
                self._normalize_title(item.get("title", ""))
                for item in self._history
                if isinstance(item, dict) and item.get("title")
            }
            self._seen_urls = {
                self._normalize_url(item.get("url", ""))
                for item in self._history
                if isinstance(item, dict) and item.get("url")
            }

    def save(self):
        with self._lock:
            try:
                dir_path = os.path.dirname(os.path.abspath(self.filepath))
                os.makedirs(dir_path, exist_ok=True)
                tmp_file = f"{self.filepath}.tmp"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "count": len(self._seen_ids),
                        "seen_ids": list(self._seen_ids),
                        "seen_urls": list(self._seen_urls),
                        "history": self._history
                    }, f, ensure_ascii=False, indent=2)

                # Retry replace in case of Windows file lock
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        os.replace(tmp_file, self.filepath)
                        break
                    except PermissionError:
                        if attempt < max_retries - 1:
                            time.sleep(0.1)
                        else:
                            raise
            except Exception as e:
                logger.error(f"Failed to save seen news to {self.filepath}: {e}")

    def total_seen(self) -> int:
        with self._lock:
            return len(self._seen_ids)

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            return list(reversed(self._history[-limit:]))

    def clear(self):
        with self._lock:
            self._seen_ids.clear()
            self._seen_titles.clear()
            self._seen_urls.clear()
            self._history.clear()
            self.save()


class SubscriberManager:
    """
    Manages public subscribers for 1-on-1 direct messaging and automated news alerts.
    Persists subscribers safely to a JSON file.
    """
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._lock = threading.RLock()
        self._subscribers: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self):
        with self._lock:
            if not os.path.exists(self.filepath) or os.path.getsize(self.filepath) == 0:
                self._subscribers = {}
                return
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._subscribers = data.get("subscribers", {})
                    elif isinstance(data, list):
                        self._subscribers = {
                            str(cid): {
                                "chat_id": cid,
                                "username": "",
                                "first_name": "",
                                "active": True,
                                "joined_at": int(time.time()),
                            }
                            for cid in data
                        }
            except Exception as e:
                logger.warning(f"Error loading subscribers from {self.filepath}: {e}")
                self._subscribers = {}

    def save(self):
        with self._lock:
            try:
                dir_path = os.path.dirname(os.path.abspath(self.filepath))
                os.makedirs(dir_path, exist_ok=True)
                tmp_file = f"{self.filepath}.tmp"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "count": len(self.get_active_subscribers()),
                        "total": len(self._subscribers),
                        "subscribers": self._subscribers
                    }, f, ensure_ascii=False, indent=2)

                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        os.replace(tmp_file, self.filepath)
                        break
                    except PermissionError:
                        if attempt < max_retries - 1:
                            time.sleep(0.1)
                        else:
                            raise
            except Exception as e:
                logger.error(f"Failed to save subscribers to {self.filepath}: {e}")

    def add_subscriber(self, chat_id: Union[str, int], username: str = "", first_name: str = "") -> bool:
        """
        Registers or updates a subscriber. Returns True if newly subscribed/activated.
        """
        cid_str = str(chat_id)
        with self._lock:
            now = int(time.time())
            existing = self._subscribers.get(cid_str)
            if existing:
                was_active = existing.get("active", False)
                existing["active"] = True
                if username:
                    existing["username"] = username
                if first_name:
                    existing["first_name"] = first_name
                existing["last_interaction"] = now
                if not was_active:
                    self.save()
                    return True
                return False
            else:
                self._subscribers[cid_str] = {
                    "chat_id": chat_id,
                    "username": username,
                    "first_name": first_name,
                    "active": True,
                    "joined_at": now,
                    "last_interaction": now,
                }
                self.save()
                return True

    def remove_subscriber(self, chat_id: Union[str, int]) -> bool:
        """
        Marks a subscriber as inactive (unsubscribed).
        """
        cid_str = str(chat_id)
        with self._lock:
            if cid_str in self._subscribers:
                if self._subscribers[cid_str].get("active", True):
                    self._subscribers[cid_str]["active"] = False
                    self._subscribers[cid_str]["unsubscribed_at"] = int(time.time())
                    self.save()
                    return True
            return False

    def deactivate(self, chat_id: Union[str, int], reason: str = "") -> bool:
        """
        Deactivates subscriber if blocked or invalid.
        """
        cid_str = str(chat_id)
        with self._lock:
            if cid_str in self._subscribers and self._subscribers[cid_str].get("active", True):
                self._subscribers[cid_str]["active"] = False
                self._subscribers[cid_str]["deactivated_at"] = int(time.time())
                self._subscribers[cid_str]["deactivate_reason"] = reason
                self.save()
                return True
            return False

    def is_active(self, chat_id: Union[str, int]) -> bool:
        cid_str = str(chat_id)
        with self._lock:
            return bool(self._subscribers.get(cid_str, {}).get("active", False))

    def get_active_subscribers(self) -> List[Union[str, int]]:
        with self._lock:
            return [
                info.get("chat_id", cid)
                for cid, info in self._subscribers.items()
                if info.get("active", True)
            ]

    def total_subscribers(self) -> int:
        with self._lock:
            return sum(1 for info in self._subscribers.values() if info.get("active", True))

