import re
import json
import os
import time
import logging
import threading
from pathlib import Path
from typing import Set, List, Dict, Any, Union

logger = logging.getLogger(__name__)


class NewsSeenTracker:
    def __init__(self, filepath: str, max_items: int = 3000):
        self.filepath = filepath
        self.max_items = max_items
        self._lock = threading.RLock()
        self._seen_ids: Set[str] = set()
        self._seen_titles: Set[str] = set()
        self._history: List[Dict[str, Any]] = []
        self.load()

    def _normalize_title(self, title: str) -> str:
        if not title:
            return ""
        clean = re.sub(r"[^\w\s]", "", title.lower())
        return " ".join(clean.split())

    def load(self):
        with self._lock:
            if not os.path.exists(self.filepath) or os.path.getsize(self.filepath) == 0:
                self._seen_ids = set()
                self._seen_titles = set()
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
                    for h in self._history:
                        if isinstance(h, dict):
                            if h.get("id"):
                                self._seen_ids.add(h["id"])
                            t = h.get("title")
                            if t:
                                norm = self._normalize_title(t)
                                if norm:
                                    self._seen_titles.add(norm)
                        elif isinstance(h, str):
                            self._seen_ids.add(h)

            except Exception as e:
                logger.warning(f"Error loading seen news from {self.filepath}, starting fresh: {e}")
                self._seen_ids = set()
                self._seen_titles = set()
                self._history = []

    def is_seen(self, item_id: str, title: str = "") -> bool:
        """
        Returns True if the article has already been seen, checking both ID and normalized title.
        Prevents duplicate/double news across multiple feeds or re-runs.
        """
        with self._lock:
            if item_id and item_id in self._seen_ids:
                return True
            if title:
                norm = self._normalize_title(title)
                if norm and norm in self._seen_titles:
                    return True
            return False

    def has_seen(self, item_id: str, title: str = "") -> bool:
        return self.is_seen(item_id, title=title)

    def mark_seen(self, item_id: str, title: str = "", source: str = "") -> bool:
        if not item_id:
            return False
        norm = self._normalize_title(title)
        with self._lock:
            if item_id not in self._seen_ids and (not norm or norm not in self._seen_titles):
                self._seen_ids.add(item_id)
                if norm:
                    self._seen_titles.add(norm)
                self._history.append({
                    "id": item_id,
                    "title": title,
                    "source": source,
                    "timestamp": int(time.time())
                })
                self._prune()
                self.save()
                return True
            return False

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
                norm = self._normalize_title(title)
                if item_id and item_id not in self._seen_ids and (not norm or norm not in self._seen_titles):
                    self._seen_ids.add(item_id)
                    if norm:
                        self._seen_titles.add(norm)
                    self._history.append({
                        "id": item_id,
                        "title": title,
                        "source": source,
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

