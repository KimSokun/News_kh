# 🤖 NewsAI Telegram Alert Bot (Khmer Translation & Auto-Failover)

ប្រព័ន្ធ Telegram Bot ឆ្លាតវៃសម្រាប់តាមដាន ជ្រើសរើស និងផ្សាយព័ត៌មានបច្ចេកវិទ្យាធំៗ (AI, Cyber Security, Crypto, Tech, Forex, World News) ជាទម្រង់ Photo Card ភាសាខ្មែរទៅកាន់ **Telegram Channel** (Public & Private Channels) និង **1-on-1 Direct Subscribers** ដោយស្វ័យប្រវត្ត 24/7។

---

## 🌟 លក្ខណៈពិសេសចម្បង (Key Features)

1. **📢 Telegram Channel Full Integration**:
   - គាំទ្រការផ្សាយទៅកាន់ **Telegram Channel** មួយ ឬច្រើន (`@channel_name` ឬ `-100xxxxxxxxxx`)។
   - ភ្ជាប់មកជាមួយ **Telegram Inline Keyboard Buttons** (ប៊ូតុង "🔗 អានអត្ថបទដើម" / Read More) យ៉ាងស្រស់ស្អាតនៅខាងក្រោម Photo Card។
   - មានប្រព័ន្ធត្រួតពិនិត្យសិទ្ធិ Channel (Channel Permissions & Health Check) និងការពារ Channel Feed ដោយស្វ័យប្រវត្ត។

2. **🔥 Big News Evaluation & Filter**:
   - ត្រួតពិនិត្យ និងជ្រើសរើសតែ **ព័ត៌មានធំៗ / ទាន់ហេតុការណ៍ / High-Impact News** (Zero-days, Massive Breaches, AI Model Releases, Lawsuits, Breakthroughs)។
   - ច្រោះចោលព័ត៌មានតូចតាច, Reviews, Unboxing, Discounts ដោយស្វ័យប្រវត្ត។

3. **🖼️ HTML-Safe Khmer Photo Cards**:
   - រៀបចំ Layout យ៉ាងស្រស់ស្អាត (ចំណងជើង, សេចក្តីសង្ខេប, ចំណុចសំខាន់ៗដែលគួរដឹង, ប្រភព, Link អានដើម, កាលបរិច្ឆេទ)។
   - ប្រើប្រាស់ **Telegram HTML Mode** ការពារកុំឱ្យ Error ដោយសារសញ្ញាពិសេស (`_`, `*`, `[`, `]`, `&`)។
   - ការពារ Caption Length Limit (<= 1024 តួអក្សរ) មិនឱ្យកាត់ដាច់។

4. **📡 32+ Trusted RSS Feeds & Auto-Failover**:
   - ប្រសិនបើគ្មាន NewsAPI Key ឬ Key អស់ Quota វានឹង Switch ទៅកាន់ RSS Feeds នៃ 32+ គេហទំព័រល្បីៗ (*The Hacker News, BleepingComputer, SecurityWeek, TechCrunch, Ars Technica, The Verge, Wired, VentureBeat, CNET, TechRadar, Tom's Hardware, The Next Web, Gizmodo, The Register, SiliconANGLE, Decrypt, Cointelegraph, CoinDesk...*)។
   - ប្រព័ន្ធទាញយករូបភាព 5 ដំណាក់កាល រួមទាំង OpenGraph Fallback។

5. **🤖 AI & Translator Engine**:
   - គាំទ្រ Google Gemini AI (`gemini-3.6-flash`, `gemini-flash-latest`) សម្រាប់ Khmer Summarization។
   - Google Translate Free Fallback ដំណើរការដោយស្វ័យប្រវត្តទោះបីគ្មាន Gemini Key។

6. **🛡️ Multi-destination Broadcast & Public Subscribers**:
   - អាចផ្សាយទៅកាន់ Channel តែមួយគត់ ឬទាំង Channel និង Subscribers ផ្ទាល់។
   - គាំទ្រស្វ័យប្រវត្តនូវការចុះឈ្មោះ Subscribers នៅពេល User ចុច `/start` ឬ `/subscribe` ក្នុង Direct Chat។

---

## 🚀 របៀបតម្លើង និងប្រើប្រាស់ (Setup & Run)

### ១. តម្លើង Packages
```bash
pip install -r requirements.txt
```

### ២. បង្កើត និងកំណត់ `.env`
ចម្លងឯកសារ `.env.example` ទៅជា `.env`៖
```bash
# Windows
copy .env.example .env

# Linux / Mac
cp .env.example .env
```

កែប្រែ `.env`៖
```env
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_FROM_BOTFATHER

# កំណត់ Telegram Channel (អាចដាក់ @channel_name ឬ -100xxxxxxxxxx)
# បើមានច្រើន Channel បំបែកដោយសញ្ញាក្បៀស: @channel1,@channel2
TELEGRAM_CHANNEL_IDS=@your_channel_username

# ជម្រើសនៃការផ្សាយ (Broadcast Destinations)
BROADCAST_TO_CHANNEL=true
BROADCAST_TO_SUBSCRIBERS=true
CHANNEL_ENABLE_BUTTONS=true

# (ជម្រើស) Gemini AI Key សម្រាប់ Khmer AI Summarization
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.6-flash

# កំណត់ការ Filter & Alert
ONLY_BIG_NEWS=false
REQUIRE_PHOTO_CARD=true
POLL_INTERVAL_SECONDS=300
MAX_ALERTS_PER_CYCLE=2
```

> [!TIP]
> **របៀបកំណត់ Telegram Channel**៖
> 1. បង្កើត Channel ថ្មីលើ Telegram (ឬប្រើ Channel ដែលមានស្រាប់)។
> 2. បញ្ចូល Bot របស់អ្នកទៅក្នុង Channel នោះជា **Administrator**។
> 3. ផ្តល់សិទ្ធិ (Permission) **"Post Messages"** ដល់ Bot។
> 4. ប្រសិនបើជា Public Channel សូមចម្លង Username (ឧទាហរណ៍ `@MyTechNewsKh`) ដាក់ក្នុង `TELEGRAM_CHANNEL_IDS`។ ប្រសិនបើជា Private Channel សូមប្រើ Channel ID (ឧទាហរណ៍ `-1001234567890`)។

### ៣. តេស្តប្រព័ន្ធ និងសាកល្បងផ្ញើចូល Channel (Diagnostics)
```bash
# តេស្តប្រព័ន្ធទូទៅ (RSS Feeds, Translator, Gemini, Bot Info)
python test_news.py

# តេស្តផ្ញើ Photo Card ព័ត៌មានគំរូទៅកាន់ Telegram Channel ភ្លាមៗ
python test_news.py --channel
```

### ៤. ដំណើរការ Bot
- **Windows**: ចុចលើ `run.bat` ឬ Run:
  ```bash
  python bot.py
  ```
- **Ubuntu / Linux Server**: មើលការណែនាំក្នុង [DEPLOY_UBUNTU.md](DEPLOY_UBUNTU.md)។

