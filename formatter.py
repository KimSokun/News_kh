import re
import html
import urllib.parse
import logging
from datetime import datetime
from typing import Optional, List

import config
from news_sources import CATEGORY_ICONS_AND_TITLES

logger = logging.getLogger(__name__)

# Initialize Google GenAI client
_genai_client = None
if config.GEMINI_API_KEY:
    try:
        from google import genai
        logging.getLogger("google_genai").setLevel(logging.ERROR)
        logging.getLogger("google_genai.models").setLevel(logging.ERROR)
        _genai_client = genai.Client(api_key=config.GEMINI_API_KEY)
    except Exception as e:
        logger.warning(f"Could not initialize google-genai client: {e}")


# Check deep-translator
try:
    from deep_translator import GoogleTranslator
    _HAS_DEEP_TRANSLATOR = True
except ImportError:
    _HAS_DEEP_TRANSLATOR = False

# Minor / filler keywords to reject for "Big News Only"
_MINOR_KEYWORDS = [
    r"\bpreview\b", r"\bcomic\b", r"\btrailer\b", r"\bunboxing\b",
    r"\bdeal\b", r"\bdeals\b", r"\bdiscount\b", r"\bcoupon\b",
    r"\bhow to\b", r"\btop 5\b", r"\btop 10\b", r"\breview:\b",
    r"\bhands-on\b", r"\bwallpaper\b", r"\bgiveaway\b", r"\brumor\b",
    r"\bcase review\b", r"\baccessories for\b", r"\bhoroscope\b",
    r"\bwhat to watch\b", r"\bbest gadgets\b"
]

# Major / high-impact keywords
_BIG_KEYWORDS = [
    r"\bzero-day\b", r"\b0-day\b", r"\bcve-\b", r"\bcritical\b", r"\brecord\b",
    r"\bransomware\b", r"\bbreach\b", r"\bhack\b", r"\bhacked\b", r"\bcyberattack\b",
    r"\bbillion\b", r"\bmillion\b", r"\blawsuit\b", r"\bfine\b", r"\bban\b", r"\bbanned\b",
    r"\bfbi\b", r"\bsec\b", r"\bdoj\b", r"\bftc\b", r"\bacquisition\b", r"\bacquires\b",
    r"\blaunches\b", r"\bunveils\b", r"\breleases\b", r"\bemergency\b", r"\bvulnerability\b",
    r"\boutage\b", r"\bsettlement\b", r"\bmalware\b", r"\bbackdoor\b", r"\btrojan\b",
    r"\bexploit\b", r"\bgpt-\b", r"\bclaude-\b", r"\bgemini\b", r"\bdeepseek\b", r"\bllama\b",
    r"\bopenai\b", r"\banthropic\b", r"\bnvidia\b", r"\bapple intelligence\b",
    r"\bpatch tuesday\b", r"\bdata leak\b", r"\bespionage\b", r"\bstate-sponsored\b"
]


def extract_domain(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or "website"
    except Exception:
        return "link"


def truncate_text(text: str, max_length: int = 1000) -> str:
    if not text or len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def heuristic_is_big_news(title: str, summary: str = "") -> bool:
    """
    Evaluates whether an article qualifies as big/major news based on keyword heuristics.
    """
    combined = f"{title} {summary}".lower()

    # Reject if clear filler
    for ptn in _MINOR_KEYWORDS:
        if re.search(ptn, combined):
            return False

    # Check for big news keywords
    for ptn in _BIG_KEYWORDS:
        if re.search(ptn, combined):
            return True

    # Check for strong action indicators in substantive headlines
    if len(title.split()) >= 5:
        action_words = [
            "announces", "introduces", "investigates", "targets", "warns",
            "discovers", "discloses", "threat", "alert", "security flaw",
            "new feature", "major update", "breakthrough"
        ]
        if any(w in combined for w in action_words):
            return True

    return False


def translate_text_google(text: str, target_lang: str = "km") -> str:
    if not text or not text.strip():
        return ""

    text = text.strip()

    # Strategy 1: deep-translator
    if _HAS_DEEP_TRANSLATOR:
        try:
            res = GoogleTranslator(source="auto", target=target_lang).translate(text)
            if res and "error" not in res.lower() and "that’s all we know" not in res.lower():
                return res
        except Exception as e:
            logger.debug(f"GoogleTranslator error: {e}")

    # Strategy 2: Google Translate API endpoint
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": target_lang,
            "dt": "t",
            "q": text
        }
        res = requests.get(url, params=params, headers=headers, timeout=config.HTTP_TIMEOUT)
        if res.status_code == 200:
            data = res.json()
            translated_parts = [part[0] for part in data[0] if part and part[0]]
            result = "".join(translated_parts).strip()
            if result and "error 500" not in result.lower():
                return result
    except Exception as e:
        logger.debug(f"Free translate endpoint error: {e}")

    return text


def format_news_card_with_gemini(item: dict) -> Optional[str]:
    """
    Uses Google GenAI SDK to evaluate importance and generate rich Khmer card.
    If ONLY_BIG_NEWS is True and news is minor, returns None (rejects).
    """
    if not _genai_client:
        return None

    category = item.get("category", "tech")
    icon, cat_display = CATEGORY_ICONS_AND_TITLES.get(category, ("📰", "News"))
    source = item.get("source", "News")
    title = item.get("title_en", "")
    summary = item.get("summary_en", "")
    link = item.get("link", "")
    domain = extract_domain(link)
    is_html = config.TELEGRAM_PARSE_MODE == "HTML"

    filter_instruction = ""
    if config.ONLY_BIG_NEWS:
        filter_instruction = """
IMPORTANT FILTER RULE:
Only accept MAJOR / HIGH-IMPACT / BREAKING news (e.g. major zero-days, massive breaches, major AI model releases by Google/OpenAI/Meta/DeepSeek/Anthropic, billion-dollar fines, critical law/security events).
If this is minor filler, a routine gadget review, a comic preview, a minor tutorial, or low-impact news, output EXACTLY AND ONLY: REJECT_NOT_BIG_NEWS
"""

    if is_html:
        format_guide = f"""
Strictly follow this clean layout format in Khmer using HTML tags:
<b>{icon} [{cat_display}]៖ &lt;Khmer Headline with relevant English tech terms&gt;</b>
&lt;Khmer 1-2 sentence lead paragraph explaining the major event clearly&gt;

📌 <b>Key Takeaways (ចំណុចសំខាន់ៗ)៖</b>
• &lt;Key takeaway 1 in natural modern Khmer&gt;
• &lt;Key takeaway 2 in natural modern Khmer&gt;
• &lt;Key takeaway 3 in natural modern Khmer (if applicable)&gt;

📰 <b>ប្រភព:</b> {html.escape(source)}
🔗 <b>អានអត្ថបទដើម:</b> <a href="{link}">{domain}</a>
"""
    else:
        format_guide = f"""
Strictly follow this clean layout format in Khmer using standard text/markdown:
{icon} [{cat_display}]៖ <Khmer Headline with relevant English tech terms>
<Khmer 1-2 sentence lead paragraph explaining the major event clearly>

📌 Key Takeaways (ចំណុចសំខាន់ៗ)៖
• <Key takeaway 1 in natural modern Khmer>
• <Key takeaway 2 in natural modern Khmer>
• <Key takeaway 3 in natural modern Khmer (if applicable)>

📰 ប្រភព: {source}
🔗 អានអត្ថបទដើម: [{domain}]({link})
"""

    prompt = f"""
You are an expert technology news editor for a high-priority Telegram tech channel in Cambodia.
{filter_instruction}

Input:
Category: {cat_display}
Title: {title}
Summary/Details: {summary}
Source: {source}
Link: {link}

{format_guide}

CRITICAL LANGUAGE & WRITING RULES:
1. Write in natural, modern Cambodian Khmer. Do NOT use awkward robotic translation or Thai-influenced structures.
2. It is completely fine and recommended to keep common tech terms in English (e.g. AI, Zero-Day, Cybersecurity, Malware, Ransomware, Bug, Model, Cloud, Hack, Update, Token, Crypto, KYC) rather than forcing awkward translations.
3. Output ONLY the formatted message (or REJECT_NOT_BIG_NEWS).
4. Do not include markdown code block backticks (no ```).
5. Total text length MUST be under 950 characters.
"""

    models_to_try = []
    if config.GEMINI_MODEL:
        models_to_try.append(config.GEMINI_MODEL)
    for m in [
        "gemini-3.6-flash",
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
        "gemini-3-flash-preview",
        "gemini-2.5-flash-lite",
        "gemini-pro-latest"
    ]:
        if m not in models_to_try:
            models_to_try.append(m)

    for model_name in models_to_try:
        try:
            response = _genai_client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            text = response.text.strip()
            if "REJECT_NOT_BIG_NEWS" in text:
                logger.info(f"Gemini evaluated article as non-major news: {title}")
                return None
            if text and len(text) > 40:
                return truncate_text(text, 1000)
        except Exception as e:
            logger.debug(f"Gemini model {model_name} failed: {e}")
            continue

    return None


def format_news_card_fallback(item: dict, translate: bool = True) -> Optional[str]:
    """
    Rule-based card builder with Google Translate fallback.
    """
    # Check heuristic if ONLY_BIG_NEWS is on
    if config.ONLY_BIG_NEWS:
        if not heuristic_is_big_news(item.get("title_en", ""), item.get("summary_en", "")):
            logger.info(f"Heuristic filter rejected non-major article: {item.get('title_en')}")
            return None

    category = item.get("category", "tech")
    icon, cat_display = CATEGORY_ICONS_AND_TITLES.get(category, ("📰", "News"))
    source = item.get("source", "News")
    title_en = item.get("title_en", "").strip()
    summary_en = item.get("summary_en", "").strip()
    link = item.get("link", "")
    pub = item.get("pub", "")[:25]
    domain = extract_domain(link)
    is_html = config.TELEGRAM_PARSE_MODE == "HTML"

    if translate and title_en:
        title_km = translate_text_google(title_en, "km")
    else:
        title_km = title_en

    if translate and summary_en:
        summary_km = translate_text_google(summary_en[:350], "km")
    else:
        summary_km = summary_en[:350]

    # Split summary into bullet points
    sentences = [s.strip() for s in re.split(r"[.!?។\n]+", summary_km) if len(s.strip()) > 15]
    lead_text = sentences[0] if sentences else summary_km
    bullets = sentences[1:4] if len(sentences) > 1 else []

    if is_html:
        safe_title = html.escape(title_km)
        safe_lead = html.escape(lead_text)
        safe_source = html.escape(source)
        safe_domain = html.escape(domain)

        card_lines = [
            f"<b>{icon} [{cat_display}]៖ {safe_title}</b>",
            "",
            safe_lead
        ]

        if bullets:
            card_lines.append("")
            card_lines.append("📌 <b>Key Takeaways (ចំណុចសំខាន់ៗ)៖</b>")
            for b in bullets:
                card_lines.append(f"• {html.escape(b)}")

        card_lines.extend([
            "",
            f"📰 <b>ប្រភព:</b> {safe_source}",
        ])

        if link:
            card_lines.append(f"🔗 <b>អានអត្ថបទដើម:</b> <a href=\"{link}\">{safe_domain}</a>")
        if pub:
            card_lines.append(f"📅 {html.escape(pub)}")
    else:
        card_lines = [
            f"{icon} [{cat_display}]៖ {title_km}",
            "",
            lead_text
        ]

        if bullets:
            card_lines.append("")
            card_lines.append("📌 Key Takeaways (ចំណុចសំខាន់ៗ)៖")
            for b in bullets:
                card_lines.append(f"• {b}")

        card_lines.extend([
            "",
            f"📰 ប្រភព: {source}",
        ])

        if link:
            card_lines.append(f"🔗 អានអត្ថបទដើម: [{domain}]({link})")
        if pub:
            card_lines.append(f"📅 {pub}")

    result = "\n".join(card_lines)
    return truncate_text(result, 1000)


def format_news_card(item: dict, translate_to_khmer: bool = True) -> Optional[str]:
    """
    Master formatter:
    1. Tries Gemini AI with Big News evaluation.
    2. Falls back to Google Translate with heuristic big-news filtering.
    3. Returns None if the article is not big news or failed formatting.
    """
    if translate_to_khmer and config.GEMINI_API_KEY:
        ai_card = format_news_card_with_gemini(item)
        if ai_card:
            return ai_card
        elif config.ONLY_BIG_NEWS:
            # If Gemini evaluated it as not big news, return None
            return None

    return format_news_card_fallback(item, translate=translate_to_khmer)

