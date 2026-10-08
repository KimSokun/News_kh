import re

_TRANSLATE_RE = re.compile(
    r"\b(translate|translation|prakal|convert to khmer|to khmer|to english|say in khmer|"
    r"khmer version|khmer translation)\b|"
    r"(/translate\b|translate:|បកប្រែ|ប្រែភាសា|ប្រែសម្រួល|បកប្រែជាភាសាខ្មែរ)",
    re.IGNORECASE
)

_TRANSLATE_PREFIX_RE = re.compile(
    r"^(?:/translate\s+|please\s+translate\s+|translate\s*[:\-]?\s*|prakal\s*[:\-]?\s*|បកប្រែ\s*[:\-]?\s*|ប្រែភាសា\s*[:\-]?\s*)",
    re.IGNORECASE
)


def is_translate_request(text: str) -> bool:
    if not text:
        return False
    return bool(_TRANSLATE_RE.search(text))


def detect_translate_request(text: str) -> bool:
    return is_translate_request(text)


def extract_translate_text(text: str) -> str:
    cleaned = _TRANSLATE_PREFIX_RE.sub("", text).strip()
    return cleaned if cleaned else text.strip()


def extract_auto_translate_text(text: str) -> str:
    return text.strip()


_NEWS_RE = re.compile(
    r"\b(news|latest|breaking|headline|today.?s news|"
    r"what.?s happening|tech news|technology news|ai news|"
    r"forex|exchange rate|currency|stock market|wall street|crypto news|"
    r"usa news|america news|us news|world news|global news|big news|"
    r"security news|cyber news|tech update)\b|"
    r"(ព័ត៌មាន|ដំណឹង|ថ្មីៗ|ព័ត៌មានថ្មី|ទាន់ហេតុការណ៍|ព័ត៌មានបច្ចេកវិទ្យា|ព័ត៌មានអន្តរជាតិ|ព័ត៌មានពិភពលោក)",
    re.IGNORECASE
)

_NEWS_CATEGORY_MAP = {
    "ai": [
        r"\bai\b", r"\bai tool", r"\bartificial intelligence\b", r"\bchatgpt\b",
        r"\bopenai\b", r"\bllm\b", r"\bmachine learning\b", r"\bdeepseek\b",
        r"\bclaude\b", r"\bgemini\b", r"\bgenerative ai\b", r"\banthropic\b",
        r"\bdeepmind\b", r"\bnvidia\b", r"\bhugging face\b", r"\bhuggingface\b",
        r"\bsemianalysis\b", r"បញ្ញាសិប្បនិម្មិត", r"អេអាយ", r"ព័ត៌មាន\s*ai"
    ],
    "security": [
        r"\bsecurity\b", r"\bhacker\b", r"\bmalware\b", r"\bransomware\b",
        r"\bcyber\b", r"\bbreach\b", r"\bcve\b", r"\bvulnerability\b",
        r"\bcyberattack\b", r"\bzero-day\b", r"\binfosec\b",
        r"សន្តិសុខ", r"ហេគ", r"មេរោគ", r"ហេគឃ័រ", r"សន្តិសុខអ៊ីនធឺណិត", r"សុវត្ថិភាព"
    ],
    "crypto": [
        r"\bcrypto\b", r"\bbitcoin\b", r"\bethereum\b", r"\bblockchain\b",
        r"\bweb3\b", r"\bdecrypt\b", r"\bcointelegraph\b", r"\bbtc\b", r"\beth\b",
        r"គ្រីបតូ", r"ប៊ីតខយ", r"កាក់", r"ប្លុកឆេន"
    ],
    "tech": [
        r"\btech\b", r"\btechnology\b", r"\bgadget\b", r"\bstartup\b",
        r"\bsoftware\b", r"\bhardware\b", r"\brobot\b", r"\bapple\b",
        r"\bgoogle\b", r"\bmicrosoft\b", r"\bsamsung\b", r"\bhacker news\b",
        r"\bycombinator\b", r"\btechmeme\b", r"\bzdnet\b",
        r"បច្ចេកវិទ្យា", r"ទូរស័ព្ទ", r"កុំព្យូទ័រ", r"កម្មវិធី"
    ],
    "forex": [
        r"\bforex\b", r"\bcurrency\b", r"\bexchange rate\b", r"\busd\b",
        r"\beur\b", r"\bgold\b", r"\bstock market\b", r"\bwall street\b",
        r"អត្រាប្តូរប្រាក់", r"ហាងឆេងមាស", r"ទីផ្សារហិរញ្ញវត្ថុ", r"ភាគហ៊ុន"
    ],
    "usa": [
        r"\busa\b", r"\bu\.s\.\b", r"\bamerica\b", r"\bus news\b",
        r"\bunited states\b", r"\bwhite house\b", r"\bwashington\b", r"\bcongress\b",
        r"សហរដ្ឋអាមេរិក", r"អាមេរិក"
    ],
    "business": [
        r"\bbusiness\b", r"\bmarket\b", r"\bstartup\b", r"\bfinance\b",
        r"\beconomy\b", r"\binvestment\b",
        r"ពាណិជ្ជកម្ម", r"សេដ្ឋកិច្ច", r"ហិរញ្ញវត្ថុ", r"វិនិយោគ"
    ],
    "auto": [
        r"\bauto\b", r"\bcar\b", r"\bcars\b", r"\bev\b", r"\belectric vehicle\b",
        r"\btesla\b", r"\bautomotive\b",
        r"ឡាន", r"រថយន្ត", r"យានយន្ត", r"ឡានអគ្គិសនី"
    ],
    "world": [
        r"\bworld\b", r"\bglobal\b", r"\binternational\b", r"\bbig news\b", r"\bbreaking\b",
        r"ពិភពលោក", r"អន្តរជាតិ", r"ព័ត៌មានពិភពលោក"
    ],
    "science": [
        r"\bscience\b", r"\bspace\b", r"\bnasa\b", r"\bresearch\b",
        r"វិទ្យាសាស្ត្រ", r"អវកាស"
    ],
    "health": [
        r"\bhealth\b", r"\bmedical\b", r"\bmedicine\b",
        r"សុខភាព", r"វេជ្ជសាស្ត្រ"
    ],
}

TRUSTED_NEWS_SOURCES = {
    # Hacker News & Tech Aggregators
    "hackernews": {
        "name": "Hacker News (YC)",
        "url": "https://news.ycombinator.com/",
        "rss": "https://hnrss.org/frontpage"
    },
    "techmeme": {
        "name": "Techmeme",
        "url": "https://www.techmeme.com/",
        "rss": "https://www.techmeme.com/feed.xml"
    },

    # AI Companies & Leading AI Labs
    "openai": {
        "name": "OpenAI News & Research",
        "url": "https://openai.com/news/",
        "rss": "https://openai.com/news/rss.xml"
    },
    "deepmind": {
        "name": "Google DeepMind",
        "url": "https://deepmind.google/discover/blog/",
        "rss": "https://deepmind.google/blog/rss.xml"
    },
    "google_ai": {
        "name": "Google AI Blog",
        "url": "https://blog.google/technology/ai/",
        "rss": "https://blog.google/technology/ai/rss/"
    },
    "nvidia_ai": {
        "name": "NVIDIA AI & Deep Learning",
        "url": "https://blogs.nvidia.com/",
        "rss": "https://blogs.nvidia.com/blog/category/deep-learning/feed/"
    },
    "microsoft": {
        "name": "Microsoft Official Blog",
        "url": "https://blogs.microsoft.com/",
        "rss": "https://blogs.microsoft.com/feed/"
    },
    "huggingface": {
        "name": "Hugging Face Blog",
        "url": "https://huggingface.co/blog",
        "rss": "https://huggingface.co/blog/feed.xml"
    },
    "mit_ai": {
        "name": "MIT Technology Review - AI",
        "url": "https://www.technologyreview.com/topic/artificial-intelligence/",
        "rss": "https://www.technologyreview.com/topic/artificial-intelligence/feed"
    },
    "towardsai": {
        "name": "Towards AI",
        "url": "https://towardsai.net/",
        "rss": "https://towardsai.net/feed"
    },
    "semianalysis": {
        "name": "SemiAnalysis (AI & Chips)",
        "url": "https://semianalysis.com/",
        "rss": "https://newsletter.semianalysis.com/feed"
    },
    "theverge_ai": {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/ai-artificial-intelligence",
        "rss": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"
    },
    "siliconangle_ai": {
        "name": "SiliconANGLE AI",
        "url": "https://siliconangle.com/category/ai/",
        "rss": "https://siliconangle.com/category/ai/feed/"
    },
    "techcrunch_ai": {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/",
        "rss": "https://techcrunch.com/category/artificial-intelligence/feed/"
    },

    # Cyber Security
    "thehackernews": {
        "name": "The Hacker News",
        "url": "https://thehackernews.com/",
        "rss": "https://thehackernews.com/feeds/posts/default"
    },
    "bleepingcomputer": {
        "name": "BleepingComputer",
        "url": "https://www.bleepingcomputer.com/",
        "rss": "https://www.bleepingcomputer.com/feed/"
    },
    "securityweek": {
        "name": "SecurityWeek",
        "url": "https://www.securityweek.com/",
        "rss": "https://www.securityweek.com/feed/"
    },
    "gbhackers": {
        "name": "GBHackers",
        "url": "https://gbhackers.com/",
        "rss": "https://gbhackers.com/feed/"
    },
    "infosecurity": {
        "name": "Infosecurity Magazine",
        "url": "https://www.infosecurity-magazine.com/",
        "rss": "https://www.infosecurity-magazine.com/rss/news/"
    },
    "darkreading": {
        "name": "Dark Reading",
        "url": "https://www.darkreading.com/",
        "rss": "https://www.darkreading.com/rss.xml"
    },

    # Tech & General Technology
    "techcrunch": {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/",
        "rss": "https://techcrunch.com/feed/"
    },
    "arstechnica": {
        "name": "Ars Technica",
        "url": "https://arstechnica.com/",
        "rss": "https://feeds.arstechnica.com/arstechnica/index"
    },
    "theverge": {
        "name": "The Verge",
        "url": "https://theverge.com/",
        "rss": "https://www.theverge.com/rss/index.xml"
    },
    "wired": {
        "name": "Wired",
        "url": "https://www.wired.com/",
        "rss": "https://www.wired.com/feed/rss"
    },
    "engadget": {
        "name": "Engadget",
        "url": "https://www.engadget.com/",
        "rss": "https://www.engadget.com/rss.xml"
    },
    "marktechpost": {
        "name": "MarkTechPost",
        "url": "https://www.marktechpost.com/",
        "rss": "https://www.marktechpost.com/feed/"
    },
    "macrumors": {
        "name": "MacRumors",
        "url": "https://www.macrumors.com/",
        "rss": "https://www.macrumors.com/macrumors.xml"
    },
    "venturebeat": {
        "name": "VentureBeat",
        "url": "https://venturebeat.com/",
        "rss": "https://venturebeat.com/feed/"
    },
    "cnet": {
        "name": "CNET",
        "url": "https://www.cnet.com/",
        "rss": "https://www.cnet.com/rss/news/"
    },
    "techradar": {
        "name": "TechRadar",
        "url": "https://www.techradar.com/",
        "rss": "https://www.techradar.com/rss"
    },
    "tomshardware": {
        "name": "Tom's Hardware",
        "url": "https://www.tomshardware.com/",
        "rss": "https://www.tomshardware.com/feeds/all"
    },
    "thenextweb": {
        "name": "The Next Web",
        "url": "https://thenextweb.com/",
        "rss": "https://thenextweb.com/feed"
    },
    "gizmodo": {
        "name": "Gizmodo",
        "url": "https://gizmodo.com/",
        "rss": "https://gizmodo.com/rss"
    },
    "theregister": {
        "name": "The Register",
        "url": "https://www.theregister.com/",
        "rss": "https://www.theregister.com/headlines.atom"
    },
    "siliconangle": {
        "name": "SiliconANGLE",
        "url": "https://siliconangle.com/",
        "rss": "https://siliconangle.com/feed/"
    },
    "9to5google": {
        "name": "9to5Google",
        "url": "https://9to5google.com/",
        "rss": "https://9to5google.com/feed/"
    },
    "androidpolice": {
        "name": "Android Police",
        "url": "https://www.androidpolice.com/",
        "rss": "https://www.androidpolice.com/feed/"
    },
    "xda": {
        "name": "XDA Developers",
        "url": "https://www.xda-developers.com/",
        "rss": "https://www.xda-developers.com/feed/"
    },
    "ainews": {
        "name": "AI News",
        "url": "https://www.artificialintelligence-news.com/",
        "rss": "https://www.artificialintelligence-news.com/feed/"
    },
    "readwrite": {
        "name": "ReadWrite",
        "url": "https://readwrite.com/",
        "rss": "https://readwrite.com/feed/"
    },
    "hackernoon": {
        "name": "HackerNoon",
        "url": "https://hackernoon.com/",
        "rss": "https://hackernoon.com/feed"
    },
    "zdnet": {
        "name": "ZDNet",
        "url": "https://www.zdnet.com/",
        "rss": "https://www.zdnet.com/news/rss.xml"
    },

    # Crypto & Web3
    "decrypt": {
        "name": "Decrypt",
        "url": "https://decrypt.co/",
        "rss": "https://decrypt.co/feed"
    },
    "cointelegraph": {
        "name": "Cointelegraph",
        "url": "https://cointelegraph.com/",
        "rss": "https://cointelegraph.com/rss"
    },
    "coindesk": {
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/",
        "rss": "https://www.coindesk.com/arc/outboundfeeds/rss/"
    },

    # EV & Automotive
    "electrek": {
        "name": "Electrek",
        "url": "https://electrek.co/",
        "rss": "https://electrek.co/feed/"
    },
    "caranddriver": {
        "name": "Car and Driver",
        "url": "https://www.caranddriver.com/",
        "rss": "https://www.caranddriver.com/rss/all.xml/"
    },
}

NEWS_CATEGORY_SOURCES = {
    "security": ["thehackernews", "bleepingcomputer", "securityweek", "gbhackers", "infosecurity", "darkreading"],
    "cyber": ["thehackernews", "bleepingcomputer", "securityweek", "gbhackers", "infosecurity", "darkreading"],
    "ai": [
        "openai", "deepmind", "google_ai", "nvidia_ai", "huggingface", "mit_ai", "towardsai",
        "semianalysis", "theverge_ai", "siliconangle_ai", "techcrunch_ai",
        "thehackernews", "marktechpost", "venturebeat", "ainews", "techcrunch", "arstechnica",
        "theverge", "wired", "siliconangle", "hackernoon"
    ],
    "tech": [
        "hackernews", "techmeme", "openai", "google_ai", "deepmind", "nvidia_ai", "microsoft", "zdnet",
        "thehackernews", "techcrunch", "theverge", "arstechnica", "wired", "engadget", "venturebeat",
        "cnet", "techradar", "tomshardware", "thenextweb", "gizmodo", "theregister",
        "siliconangle", "9to5google", "androidpolice", "xda", "macrumors", "readwrite", "hackernoon"
    ],
    "technology": [
        "hackernews", "techmeme", "openai", "google_ai", "deepmind", "nvidia_ai", "microsoft", "zdnet",
        "thehackernews", "techcrunch", "theverge", "arstechnica", "wired", "engadget", "venturebeat",
        "cnet", "techradar", "tomshardware", "thenextweb", "gizmodo", "theregister",
        "siliconangle", "9to5google", "androidpolice", "xda", "macrumors", "readwrite", "hackernoon"
    ],
    "crypto": ["cointelegraph", "decrypt", "coindesk"],
    "forex": ["cointelegraph", "decrypt", "techcrunch"],
    "business": ["techcrunch", "theverge", "arstechnica", "venturebeat", "coindesk"],
    "auto": ["electrek", "caranddriver", "theverge"],
    "car": ["electrek", "caranddriver", "theverge"],
    "world": ["hackernews", "techmeme", "thehackernews", "bleepingcomputer", "techcrunch", "arstechnica", "theverge", "theregister"],
    "usa": ["hackernews", "techcrunch", "theverge", "arstechnica", "bleepingcomputer", "cnet"],
    "science": ["arstechnica", "wired", "marktechpost", "gizmodo", "deepmind"],
    "health": ["arstechnica", "theverge", "wired"],
}

CATEGORY_ICONS_AND_TITLES = {
    "tech": ("📱", "Technology"),
    "ai": ("🤖", "AI & LLM Tools"),
    "security": ("🛡️", "Cyber Security"),
    "cyber": ("🛡️", "Cyber Security"),
    "crypto": ("₿", "Crypto & Web3"),
    "forex": ("💱", "Forex & Finance"),
    "business": ("💼", "Business"),
    "auto": ("🚗", "EV & Automotive"),
    "car": ("🚗", "EV & Automotive"),
    "world": ("🌍", "World News"),
    "usa": ("🇺🇸", "U.S. News"),
    "science": ("🔬", "Science"),
    "health": ("🏥", "Health"),
}


def detect_news_category(text: str) -> str:
    lower = (text or "").lower().strip()
    aliases = {
        "us": "usa", "u.s.": "usa", "u.s": "usa", "america": "usa",
        "technology": "tech", "cyber": "security", "cybersecurity": "security",
        "infosec": "security", "ai tool": "ai", "ai tools": "ai",
        "crypto news": "crypto", "cars": "auto", "vehicle": "auto", "ev": "auto",
        "finance": "business", "market": "business",
    }
    if lower in aliases:
        return aliases[lower]
    if lower in NEWS_CATEGORY_SOURCES:
        return lower
    for cat, patterns in _NEWS_CATEGORY_MAP.items():
        for ptn in patterns:
            if re.search(ptn, lower):
                return cat
    return "tech"
