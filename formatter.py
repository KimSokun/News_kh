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


def truncate_text(text: str, max_length: int = 1020) -> str:
    if not text or len(text) <= max_length:
        return text
    truncated = text[:max_length - 3]
    # If cut in the middle of an HTML tag, roll back to before '<'
    last_open = truncated.rfind("<")
    last_close = truncated.rfind(">")
    if last_open > last_close:
        truncated = truncated[:last_open]
    return truncated.rstrip() + "..."


_THAI_LAO_WORD_MAP = {
    "កกำลัง": "កំពុង",
    "กำลัง": "កំពុង",
    "បាន": "បាន",
    "បាន": "បាន",
}

_LAO_THAI_TO_KHMER = {
    'ຊ': 'ជ', 'ຕ': 'ត', 'ດ': 'ដ', 'ບ': 'ប', 'ປ': 'ប៉',
    'ຜ': 'ផ', 'ຝ': 'ហ្វ', 'ພ': 'ព', 'ຟ': 'ហ្វ', 'ມ': 'ម',
    'ຍ': 'យ', 'ຣ': 'រ', 'ລ': 'ល', 'ວ': 'វ', 'ສ': 'ស',
    'ຫ': 'ហ', 'ອ': 'អ', 'ຮ': 'ហ', 'ຯ': '។', 'ໆ': 'ៗ',
}


def sanitize_khmer_script(text: str) -> str:
    """
    Sanitizes inadvertent Lao/Thai character bleed in LLM multilingual output.
    """
    if not text:
        return ""
    # Replace common Thai bleed words
    for tw, kw in _THAI_LAO_WORD_MAP.items():
        if tw in text:
            text = text.replace(tw, kw)
    for src, dst in _LAO_THAI_TO_KHMER.items():
        if src in text:
            text = text.replace(src, dst)
    # Strip any foreign scripts that LLMs sometimes bleed (Devanagari \u0900-\u097F, Thai \u0E00-\u0E7F, Lao \u0E80-\u0EFF, Myanmar \u1000-\u109F)
    text = re.sub(r"[\u0900-\u097F\u0E00-\u0E7F\u0E80-\u0EFF\u1000-\u109F]", "", text)
    return text


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
Strictly follow this layout format in Bilingual (Khmer in front, followed by English) using HTML tags:
<b>[&lt;Smart Khmer Event Tag, e.g. បញ្ញាសិប្បនិម្មិត, ដាច់សេវា, សុវត្ថិភាព, បច្ចេកវិទ្យា, គ្រីបតូ&gt;]៖ &lt;Khmer Headline with relevant emoji&gt;</b>
<i>&lt;Original English Headline&gt;</i>

&lt;Khmer 1 concise sentence explaining the core event clearly&gt;
<i>&lt;English 1 concise sentence summary&gt;</i>

📌 <b>ចំណុចសំខាន់ៗ៖</b>
• &lt;Key takeaway 1 in short natural modern Khmer (max 15 words)&gt;
  ↳ <i>&lt;Key takeaway 1 in short English (max 15 words)&gt;</i>
• &lt;Key takeaway 2 in short natural modern Khmer (max 15 words)&gt;
  ↳ <i>&lt;Key takeaway 2 in short English (max 15 words)&gt;</i>

💡 <b>គន្លឹះ៖</b> &lt;Khmer practical tip or actionable advice for readers&gt;
<i>[Tip: &lt;English concise practical tip or advice&gt;]</i>

🌐 <b>ប្រភព:</b> {html.escape(source)}
⚡ <b>ស្ថានភាព:</b> &lt;Smart Contextual Status: choose matching status such as ព័ត៌មានផ្លូវការ (Official) / ទាន់ហេតុការណ៍ (Breaking) / ការព្រមាន (Security Alert) / ផ្ទៀងផ្ទាត់រួចរាល់ (Verified)&gt;
🔗 <b>អានលម្អិត:</b> <a href="{link}">{domain}</a>
"""
    else:
        format_guide = f"""
Strictly follow this layout format in Bilingual (Khmer in front, followed by English) using standard text/markdown:
[&lt;Smart Khmer Event Tag&gt;]៖ &lt;Khmer Headline with relevant emoji&gt;
(&lt;Original English Headline&gt;)

&lt;Khmer 1 concise sentence explaining the core event clearly&gt;
(&lt;English 1 concise sentence summary&gt;)

📌 ចំណុចសំខាន់ៗ៖
• &lt;Key takeaway 1 in short natural modern Khmer (max 15 words)&gt;
  ↳ &lt;Key takeaway 1 in short English (max 15 words)&gt;
• &lt;Key takeaway 2 in short natural modern Khmer (max 15 words)&gt;
  ↳ &lt;Key takeaway 2 in short English (max 15 words)&gt;

💡 គន្លឹះ៖ &lt;Khmer practical tip or actionable advice for readers&gt;
[Tip: &lt;English concise practical tip or advice&gt;]

🌐 ប្រភព: {source}
⚡ ស្ថានភាព: &lt;Smart Contextual Status&gt;
🔗 អានលម្អិត: [{domain}]({link})
"""

    prompt = f"""
You are an expert bilingual technology news editor for a high-priority Telegram tech channel in Cambodia.
{filter_instruction}

Input:
Category: {cat_display}
Title: {title}
Summary/Details: {summary}
Source: {source}
Link: {link}

{format_guide}

CRITICAL LANGUAGE & WRITING RULES:
1. Always put Khmer text in FRONT / FIRST, followed by English right below it.
2. The header tag must be in brackets in Khmer matching the topic (e.g. [បញ្ញាសិប្បនិម្មិត], [ដាច់សេវា], [សុវត្ថិភាព], [បច្ចេកវិទ្យា], [គ្រីបតូ]).
3. Include 💡 គន្លឹះ / Tip offering actionable advice or insight for tech users.
4. For ⚡ ស្ថានភាព, intelligently select the most fitting smart status (e.g. ព័ត៌មានផ្លូវការ, ទាន់ហេតុការណ៍, ការព្រមានបន្ទាន់, ឬ ផ្ទៀងផ្ទាត់រួចរាល់).
5. Write strictly in standard Cambodian Khmer script (អក្សរខ្មែរ). DO NOT use or mix any Lao, Thai, or Devanagari/Hindi characters or words. Keep common tech terms in English where natural (e.g. AI, Zero-Day, Cybersecurity, Malware, Ransomware, Bug, Model, Cloud, Hack, Update, Token, Crypto, Platform, Framework).
6. Output ONLY the formatted message (or REJECT_NOT_BIG_NEWS).
7. Do not include markdown code block backticks (no ```).
8. STRICT CONCISENESS & LENGTH BUDGET: Keep sentences short, punchy, and impactful. Khmer headline max 10 words, lead max 12 words, exactly 2 bullets max 8 words each, tip max 10 words. Total text must be ultra-concise so the message fits cleanly in Telegram photo captions (under 800 characters total) without any text truncation.
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
                text = sanitize_khmer_script(text)
                # Extract smart contextual status chosen by Gemini if present
                status_text = "ព័ត៌មានផ្លូវការ"
                status_match = re.search(r"⚡\s*(?:<b>)?\s*ស្ថានភាព:?\s*(?:</b>)?\s*([^\n<]+)", text)
                if status_match:
                    extracted = status_match.group(1).strip()
                    if extracted:
                        status_text = extracted

                # Build clean deterministic footer to avoid any truncated URLs or broken tags
                if is_html:
                    clean_footer = (
                        f"\n\n🌐 <b>ប្រភព:</b> {html.escape(source)}\n"
                        f"⚡ <b>ស្ថានភាព:</b> {status_text}\n"
                        f"🔗 <b>អានលម្អិត:</b> <a href=\"{link}\">{html.escape(domain)}</a>"
                    )
                    body_parts = re.split(r"\n+(?:🌐|⚡\s*(?:<b>)?\s*ស្ថានភាព|🔗)", text)
                    body = body_parts[0].strip()
                    budget = 1020 - len(clean_footer)
                    if len(body) > budget:
                        body = truncate_text(body, budget)
                    return body + clean_footer
                else:
                    clean_footer = (
                        f"\n\n🌐 ប្រភព: {source}\n"
                        f"⚡ ស្ថានភាព: {status_text}\n"
                        f"🔗 អានលម្អិត: [{domain}]({link})"
                    )
                    body_parts = re.split(r"\n+(?:🌐|⚡\s*ស្ថានភាព|🔗)", text)
                    body = body_parts[0].strip()
                    budget = 1020 - len(clean_footer)
                    if len(body) > budget:
                        body = truncate_text(body, budget)
                    return body + clean_footer
        except Exception as e:
            logger.debug(f"Gemini model {model_name} failed: {e}")
            continue

    return None


def format_news_card_fallback(item: dict) -> Optional[str]:
    """
    Standard rule-based card builder (pure Gemini AI is used for Khmer translation;
    this fallback formats a clean original card without Google Translate if Gemini is unreachable).
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

    # Split summary into lead and bullet points
    raw_sentences = [s.strip() for s in re.split(r"[.!?\n]+", summary_en) if len(s.strip()) > 15]
    lead_en = raw_sentences[0] if raw_sentences else summary_en[:250]
    lead_en = truncate_text(lead_en, 250)
    bullets_en = [truncate_text(b, 150) for b in raw_sentences[1:4]] if len(raw_sentences) > 1 else []

    if is_html:
        safe_title = html.escape(title_en)
        safe_lead = html.escape(lead_en)
        safe_source = html.escape(source)
        safe_domain = html.escape(domain)

        card_lines = [
            f"<b>[{cat_display}]៖ {safe_title}</b>",
            "",
            safe_lead
        ]

        if bullets_en:
            card_lines.append("")
            card_lines.append("📌 <b>ចំណុចសំខាន់ៗ៖</b>")
            for b in bullets_en:
                card_lines.append(f"• {html.escape(b)}")

        card_lines.extend([
            "",
            f"🌐 <b>ប្រភព:</b> {safe_source}",
            "⚡ <b>ស្ថានភាព:</b> ព័ត៌មានផ្លូវការ (Official)",
            f"🔗 <b>អានលម្អិត:</b> <a href=\"{link}\">{safe_domain}</a>"
        ])
    else:
        card_lines = [
            f"[{cat_display}]៖ {title_en}",
            "",
            lead_en
        ]

        if bullets_en:
            card_lines.append("")
            card_lines.append("📌 ចំណុចសំខាន់ៗ៖")
            for b in bullets_en:
                card_lines.append(f"• {b}")

        card_lines.extend([
            "",
            f"🌐 ប្រភព: {source}",
            "⚡ ស្ថានភាព: ព័ត៌មានផ្លូវការ (Official)",
            f"🔗 អានលម្អិត: [{domain}]({link})"
        ])

    result = "\n".join(card_lines)
    return truncate_text(result, 1020)


def format_news_card(item: dict, translate_to_khmer: bool = True) -> Optional[str]:
    """
    Master formatter:
    1. Uses Gemini AI for Khmer + English bilingual card & Big News evaluation.
    2. Does NOT use Google Translate.
    3. Falls back to clean standard card if Gemini is unavailable.
    """
    if translate_to_khmer and config.GEMINI_API_KEY:
        ai_card = format_news_card_with_gemini(item)
        if ai_card:
            return ai_card
        elif config.ONLY_BIG_NEWS:
            # If Gemini evaluated it as not big news, return None
            return None

    return format_news_card_fallback(item)

