# 🐧 ការណែនាំ Deploy NewsAI Telegram Bot លើ Ubuntu / aaPanel (/www/wwwroot/news)

ការណែនាំលម្អិតអំពីរបៀប Deploy NewsAI Telegram Bot ទៅកាន់ Server Ubuntu ឬ aaPanel Folder `/www/wwwroot/news` ដំណើរការ 24/7 គ្មានការរអាក់រអួល។

---

## 📋 ជំហានទី១: Upload Code ទៅកាន់ `/www/wwwroot/`
1. ចូលទៅកាន់ **aaPanel** -> ម៉ឺនុយខាងឆ្វេងជ្រើសរើស **Files** -> បើក Folder `/www/wwwroot/`
2. ចុច **Upload** ឯកសារ `news.zip` (ឬ Folder `news`)
3. ចុច **Uncompress** (ពន្លា) ទៅកាន់ Folder ឈ្មោះ **`news`** (ផ្លូវ: `/www/wwwroot/news`)
4. កែប្រែឯកសារ **`.env`** ដោយកំណត់៖
   - `TELEGRAM_BOT_TOKEN=...` (បានពី @BotFather)
   - `GEMINI_API_KEY=...` (ជម្រើស AI Summarization)
   - រួចចុច **Save**។

---

## ⚙️ ជំហានទី២: Setup & Run តាម aaPanel Terminal (ត្រឹមតែ ១ នាទី)

បើក **Terminal** ក្នុង aaPanel រួច Run Commands ខាងក្រោម៖

```bash
cd /www/wwwroot/news
chmod +x deploy_ubuntu.sh
./deploy_ubuntu.sh
```

---

## 🧪 ជំហានទី៣: តេស្តប្រព័ន្ធ (Diagnostics)

មុននឹងបើកដំណើរការ Service អ្នកអាចតេស្ត Feeds និង AI៖
```bash
./venv/bin/python test_news.py
```

---

## 🚀 ជំហានទី៤: បើកដំណើរការ Service 24/7 (Systemd)

```bash
sudo cp newsai.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable newsai
sudo systemctl start newsai
sudo systemctl status newsai
```

---

## 📊 របៀបគ្រប់គ្រង Service:
- **Restart Bot**: `sudo systemctl restart newsai`
- **Stop Bot**: `sudo systemctl stop newsai`
- **Check Status**: `sudo systemctl status newsai`
- **មើល Live Log**:
  ```bash
  journalctl -u newsai -f
  # ឬ
  tail -f /www/wwwroot/news/bot.log
  ```

