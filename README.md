# Thryvix Lead Bot v3 🚀

AI-powered WhatsApp bot to convert ad leads into clients, built with Flask, Twilio, and OpenAI.

## ✨ Features
- 🌐 Malayalam / English selection
- 🤖 Real-time AI replies (sales-focused)
- 📊 Lead scoring (0–100) with Telegram + Email alerts
- 🗄️ Free Postgres DB for leads & messages
- 📈 Google Sheets sync (`Thryvix_Leads`)
- ⏱️ Auto follow-up after 2 hours
- 📊 Secure dashboard with login (`admin` / `thryvixai@9495`)
- 📤 CSV export
- 🧠 Malayalam script + Manglish support

## 🛠️ Environment Variables
Set these in Render:
- `OPENAI_API_KEY`
- `OPENAI_MODEL=gpt-4o-mini`
- `BOT_WHATSAPP_NUMBER` (your Twilio sandbox number)
- `DATABASE_URL` (Postgres from Render)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SENDER_EMAIL=contact.thryvixai@gmail.com`
- `SENDER_PASSWORD` (your Gmail App Password)
- `ALERT_EMAIL=contact.thryvixai@gmail.com`
- `GOOGLE_SERVICE_JSON` (Google Sheets credentials JSON)
- `LEAD_ALERT_THRESHOLD=70`

## 🚀 Deployment (Render)
1. Push this project to GitHub  
2. Create a new Web Service on Render  
3. Build command: `pip install -r requirements.txt`  
4. Start command: `gunicorn app:app`  
5. Set environment variables above

## 📡 Twilio Setup
In your Twilio WhatsApp sandbox:
- “When a message comes in” → `https://YOUR-RENDER-URL/whatsapp`

## 📊 Dashboard
Visit `https://YOUR-RENDER-URL/dashboard`  
Login: `admin` / `thryvixai@9495`

