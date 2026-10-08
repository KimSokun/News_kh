import re
import html
import time
import logging
from typing import Optional, Union, Dict, Any, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config


logger = logging.getLogger(__name__)


# =============================================================================
# TELEGRAM HTML HELPERS
# =============================================================================

_TELEGRAM_ALLOWED_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "code",
    "pre",
    "a",
    "blockquote",
}


def _strip_html_tags(text: str) -> str:
    """
    Converts Telegram HTML caption/message into plain text.

    Also decodes HTML entities such as:
        &amp; -> &
        &lt;  -> <
        &gt;  -> >
    """

    if not text:
        return ""

    clean = re.sub(
        r"<[^>]+>",
        "",
        text
    )

    return html.unescape(
        clean
    )


def _normalize_plain_text(text: str) -> str:
    """
    Produces safe plain text for Telegram fallback.
    """

    if not text:
        return ""

    text = _strip_html_tags(
        text
    )

    # Remove invisible control characters except newline/tab.
    text = "".join(
        ch
        for ch in text
        if (
            ch in ("\n", "\r", "\t")
            or ord(ch) >= 32
        )
    )

    return text.strip()


def _is_telegram_parse_error(description: str) -> bool:
    """
    Detects Telegram formatting/entity errors.
    """

    if not description:
        return False

    desc = description.lower()

    markers = (
        "can't parse entities",
        "parse error",
        "can't find end tag",
        "unsupported start tag",
        "unsupported tag",
        "entity",
    )

    return any(
        marker in desc
        for marker in markers
    )


# =============================================================================
# TELEGRAM CLIENT
# =============================================================================

class TelegramClient:

    def __init__(
        self,
        token: Optional[str] = None
    ):

        self.token = (
            token
            or config.TELEGRAM_BOT_TOKEN
        )

        self.base_url = (
            f"https://api.telegram.org/bot{self.token}"
        )

        self.session = requests.Session()

        # ---------------------------------------------------------------------
        # Network retries
        # ---------------------------------------------------------------------

        retries = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=[
                500,
                502,
                503,
                504,
            ],
            allowed_methods=frozenset(
                [
                    "GET",
                    "POST",
                ]
            ),
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retries,
            pool_connections=10,
            pool_maxsize=10,
        )

        self.session.mount(
            "https://",
            adapter
        )

        self.session.mount(
            "http://",
            adapter
        )

        self.last_error_code: Optional[int] = None
        self.last_error_description: str = ""

    # =========================================================================
    # CONFIG
    # =========================================================================

    def is_configured(self) -> bool:
        return bool(
            self.token
            and len(self.token) > 15
        )

    # =========================================================================
    # RESPONSE HANDLING
    # =========================================================================

    def _handle_response(
        self,
        resp: requests.Response
    ) -> Dict[str, Any]:

        try:
            data = resp.json()

        except Exception:
            self.last_error_code = (
                resp.status_code
            )

            self.last_error_description = (
                f"Invalid JSON response "
                f"(HTTP {resp.status_code})"
            )

            return {
                "ok": False,
                "error": self.last_error_description,
            }

        if (
            resp.status_code != 200
            or not data.get("ok")
        ):

            self.last_error_code = (
                data.get("error_code")
                or resp.status_code
            )

            self.last_error_description = (
                data.get("description", "")
            )

        else:

            self.last_error_code = None
            self.last_error_description = ""

        # ---------------------------------------------------------------------
        # Telegram flood control
        # ---------------------------------------------------------------------

        if (
            resp.status_code == 429
            or data.get("error_code") == 429
        ):

            retry_after = (
                data.get("parameters", {})
                .get("retry_after", 5)
            )

            try:
                retry_after = int(
                    retry_after
                )
            except Exception:
                retry_after = 5

            retry_after = max(
                1,
                min(retry_after, 60)
            )

            logger.warning(
                "[Telegram] Rate limit hit. "
                f"Backing off for {retry_after}s..."
            )

            time.sleep(
                retry_after
            )

        return data

    # =========================================================================
    # BLOCKED USER
    # =========================================================================

    def is_user_blocked(self) -> bool:
        """
        Returns True if the last API call failed because:
            - user blocked bot
            - user deactivated
            - chat not found
            - bot kicked
            - bot is not a member
        """

        desc = (
            self.last_error_description
            or ""
        ).lower()

        return (
            self.last_error_code in (
                403,
                400
            )
            and any(
                k in desc
                for k in (
                    "blocked",
                    "user is deactivated",
                    "chat not found",
                    "bot was kicked",
                    "not a member",
                )
            )
        )

    # =========================================================================
    # GET ME
    # =========================================================================

    def get_me(self) -> dict:

        if not self.is_configured():
            return {
                "ok": False,
                "error": "Bot token not configured"
            }

        try:
            resp = self.session.get(
                f"{self.base_url}/getMe",
                timeout=10
            )

            return self._handle_response(
                resp
            )

        except Exception as e:
            return {
                "ok": False,
                "error": str(e)
            }

    # =========================================================================
    # SEND MESSAGE
    # =========================================================================

    def send_message(
        self,
        chat_id: Union[str, int],
        text: str,
        parse_mode: Optional[str] = None,
        disable_web_page_preview: bool = False,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:

        if not self.is_configured():

            logger.warning(
                "[Telegram] Token not set, "
                "skipping send_message"
            )

            return False

        if parse_mode is None:
            parse_mode = (
                config.TELEGRAM_PARSE_MODE
            )

        url = (
            f"{self.base_url}/sendMessage"
        )

        payload = {
            "chat_id": chat_id,
            "text": text[:4090],
            "parse_mode": parse_mode,
            "disable_web_page_preview":
                disable_web_page_preview,
        }

        if reply_markup:
            payload[
                "reply_markup"
            ] = reply_markup

        try:

            r = self.session.post(
                url,
                json=payload,
                timeout=config.HTTP_TIMEOUT
            )

            data = self._handle_response(
                r
            )

            if not data.get("ok"):

                desc = (
                    data.get(
                        "description",
                        ""
                    )
                    or ""
                ).lower()

                # -------------------------------------------------------------
                # Telegram HTML/Markdown parse error
                # -------------------------------------------------------------

                if _is_telegram_parse_error(
                    desc
                ):

                    logger.warning(
                        "[Telegram] Parse error "
                        f"({desc}), retrying as plain text"
                    )

                    fallback_payload = (
                        dict(payload)
                    )

                    fallback_payload.pop(
                        "parse_mode",
                        None
                    )

                    fallback_payload[
                        "text"
                    ] = _normalize_plain_text(
                        text
                    )[:4090]

                    r2 = self.session.post(
                        url,
                        json=fallback_payload,
                        timeout=config.HTTP_TIMEOUT
                    )

                    data2 = (
                        self._handle_response(
                            r2
                        )
                    )

                    if data2.get("ok"):
                        return True

                    logger.error(
                        "[Telegram] Plain-text retry "
                        f"also failed: "
                        f"{data2.get('description', '')}"
                    )

                    return False

                logger.error(
                    "[Telegram] send_message error: "
                    f"{data.get('description')}"
                )

                return False

            return True

        except Exception as e:

            logger.error(
                "[Telegram] send_message exception: "
                f"{e}"
            )

            return False

    # =========================================================================
    # SEND PHOTO
    # =========================================================================

    def send_photo(
        self,
        chat_id: Union[str, int],
        photo_url: str,
        caption: str = "",
        parse_mode: Optional[str] = None,
        fallback_to_text: bool = True,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:

        if not self.is_configured():

            logger.warning(
                "[Telegram] Token not set, "
                "skipping send_photo"
            )

            return False

        if parse_mode is None:
            parse_mode = (
                config.TELEGRAM_PARSE_MODE
            )

        # ---------------------------------------------------------------------
        # Invalid image -> text fallback
        # ---------------------------------------------------------------------

        if (
            not photo_url
            or not photo_url.startswith(
                ("http://", "https://")
            )
        ):

            if fallback_to_text:
                return self.send_message(
                    chat_id,
                    caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )

            logger.warning(
                "[Telegram] No valid photo URL "
                "provided and fallback_to_text "
                "is False."
            )

            return False

        url = (
            f"{self.base_url}/sendPhoto"
        )

        safe_caption = (
            caption[:1020]
        )

        payload = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": safe_caption,
            "parse_mode": parse_mode,
        }

        if reply_markup:
            payload[
                "reply_markup"
            ] = reply_markup

        try:

            r = self.session.post(
                url,
                json=payload,
                timeout=config.HTTP_TIMEOUT + 5
            )

            data = self._handle_response(
                r
            )

            if not data.get("ok"):

                desc = (
                    data.get(
                        "description",
                        ""
                    )
                    or ""
                ).lower()

                # -------------------------------------------------------------
                # Caption parse error
                # -------------------------------------------------------------

                if _is_telegram_parse_error(
                    desc
                ):

                    logger.warning(
                        "[Telegram] Photo caption "
                        "parse error, retrying without "
                        f"parse_mode: {desc}"
                    )

                    fallback_payload = (
                        dict(payload)
                    )

                    fallback_payload.pop(
                        "parse_mode",
                        None
                    )

                    fallback_payload[
                        "caption"
                    ] = _normalize_plain_text(
                        safe_caption
                    )[:1020]

                    r2 = self.session.post(
                        url,
                        json=fallback_payload,
                        timeout=config.HTTP_TIMEOUT + 5
                    )

                    data2 = (
                        self._handle_response(
                            r2
                        )
                    )

                    if data2.get("ok"):
                        return True

                    logger.warning(
                        "[Telegram] Photo plain-text "
                        "retry failed: "
                        f"{data2.get('description', '')}"
                    )

                logger.warning(
                    "[Telegram] sendPhoto failed "
                    f"({data.get('description')})"
                )

                # -------------------------------------------------------------
                # Fallback to text
                # -------------------------------------------------------------

                if fallback_to_text:

                    logger.info(
                        "[Telegram] Falling back "
                        "to text message"
                    )

                    return self.send_message(
                        chat_id,
                        caption,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup
                    )

                return False

            return True

        except Exception as e:

            logger.warning(
                "[Telegram] sendPhoto exception "
                f"({e})"
            )

            if fallback_to_text:

                return self.send_message(
                    chat_id,
                    caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )

            return False

    # =========================================================================
    # GET CHAT
    # =========================================================================

    def get_chat(
        self,
        chat_id: Union[str, int]
    ) -> Dict[str, Any]:

        if not self.is_configured():
            return {
                "ok": False,
                "error": "Bot token not configured"
            }

        try:

            resp = self.session.get(
                f"{self.base_url}/getChat",
                params={
                    "chat_id": chat_id
                },
                timeout=10
            )

            return self._handle_response(
                resp
            )

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }

    # =========================================================================
    # CHECK CHANNEL ACCESS
    # =========================================================================

    def check_channel_access(
        self,
        channel_id: Union[str, int]
    ) -> Dict[str, Any]:
        """
        Validates access to a Telegram Channel.

        Returns:
            channel details or error.
        """

        chat_info = self.get_chat(
            channel_id
        )

        if not chat_info.get("ok"):

            err = (
                chat_info.get("error")
                or self.last_error_description
            )

            return {
                "ok": False,
                "channel_id": channel_id,
                "error": (
                    f"Cannot access channel ({err}). "
                    "Ensure bot is added as Admin "
                    "with 'Post Messages' permission."
                )
            }

        res = chat_info.get(
            "result",
            {}
        )

        chat_type = res.get(
            "type",
            "unknown"
        )

        title = (
            res.get("title")
            or res.get("username")
            or str(channel_id)
        )

        username = res.get(
            "username",
            ""
        )

        return {
            "ok": True,
            "channel_id": channel_id,
            "title": title,
            "type": chat_type,
            "username": username,
            "id": res.get("id")
        }

    # =========================================================================
    # READ MORE KEYBOARD
    # =========================================================================

    @staticmethod
    def build_read_more_keyboard(
        url: str,
        button_text: str = "🔗 អានអត្ថបទដើម"
    ) -> Optional[Dict[str, Any]]:
        """
        Builds Telegram Inline Keyboard
        with a direct link button.
        """

        if not url or not url.startswith(
            ("http://", "https://")
        ):
            return None

        return {
            "inline_keyboard": [
                [
                    {
                        "text": button_text,
                        "url": url
                    }
                ]
            ]
        }

    # =========================================================================
    # DELETE MESSAGE
    # =========================================================================

    def delete_message(
        self,
        chat_id: Union[str, int],
        message_id: int
    ) -> bool:

        if not self.is_configured():
            return False

        url = (
            f"{self.base_url}/deleteMessage"
        )

        payload = {
            "chat_id": chat_id,
            "message_id": message_id
        }

        try:

            r = self.session.post(
                url,
                json=payload,
                timeout=config.HTTP_TIMEOUT
            )

            data = self._handle_response(
                r
            )

            return bool(
                data.get("ok")
            )

        except Exception as e:

            logger.error(
                "[Telegram] delete_message error: "
                f"{e}"
            )

            return False

    # =========================================================================
    # BAN CHAT MEMBER
    # =========================================================================

    def ban_chat_member(
        self,
        chat_id: Union[str, int],
        user_id: Union[str, int],
        revoke_messages: bool = False
    ) -> bool:

        if not self.is_configured():
            return False

        url = (
            f"{self.base_url}/banChatMember"
        )

        payload = {
            "chat_id": chat_id,
            "user_id": user_id,
            "revoke_messages": revoke_messages
        }

        try:

            r = self.session.post(
                url,
                json=payload,
                timeout=config.HTTP_TIMEOUT
            )

            data = self._handle_response(
                r
            )

            return bool(
                data.get("ok")
            )

        except Exception as e:

            logger.error(
                "[Telegram] ban_chat_member error: "
                f"{e}"
            )

            return False

    # =========================================================================
    # GET CHAT ADMINISTRATORS
    # =========================================================================

    def get_chat_administrators(
        self,
        chat_id: Union[str, int]
    ) -> List[int]:

        if not self.is_configured():
            return []

        url = (
            f"{self.base_url}/getChatAdministrators"
        )

        try:

            r = self.session.get(
                url,
                params={
                    "chat_id": chat_id
                },
                timeout=10
            )

            data = self._handle_response(
                r
            )

            if data.get("ok"):

                return [
                    member.get(
                        "user",
                        {}
                    ).get(
                        "id"
                    )

                    for member in data.get(
                        "result",
                        []
                    )

                    if member.get(
                        "user",
                        {}
                    ).get(
                        "id"
                    )
                ]

        except Exception as e:

            logger.debug(
                "[Telegram] "
                "get_chat_administrators error: "
                f"{e}"
            )

        return []

    # =========================================================================
    # GET UPDATES
    # =========================================================================

    def get_updates(
        self,
        offset: Optional[int] = None,
        timeout: int = 20
    ) -> list:

        if not self.is_configured():
            return []

        url = (
            f"{self.base_url}/getUpdates"
        )

        params = {
            "timeout": timeout
        }

        if offset is not None:
            params["offset"] = offset

        try:

            r = self.session.get(
                url,
                params=params,
                timeout=timeout + 5
            )

            data = self._handle_response(
                r
            )

            if data.get("ok"):
                return data.get(
                    "result",
                    []
                )

        except Exception as e:

            logger.debug(
                "[Telegram] getUpdates error: "
                f"{e}"
            )

        return []