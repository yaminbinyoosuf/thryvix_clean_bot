import os
import json
import traceback
from datetime import datetime
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import openai
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# -------------------- CONFIG --------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "supersecretkey")

# ✅ OpenAI setup (new style)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ✅ Telegram Bot Setup
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ✅ PostgreSQL DB Connection
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
cur = conn.cursor()

# ✅ Google Sheets setup (from env var instead of JSON file)
GOOGLE_CREDS = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
gc = None
if GOOGLE_CREDS:
    creds_dict = json.loads(GOOGLE_CREDS)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)

# -------------------- SAVE LEAD --------------------
def save_lead_to_db(phone, message, reply):
    try:
        cur.execute(
            "INSERT INTO leads (phone, message, ai_reply, created_at) VALUES (%s, %s, %s, %s)",
            (phone, message, reply, datetime.utcnow())
        )
        conn.commit()
    except Exception as e:
        print("❌ DB save error:", e)

def save_lead_to_sheets(phone, message, reply):
    try:
        if gc:
            sh = gc.open("Thryvix_Leads").sheet1
            sh.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), phone, message, reply])
    except Exception as e:
        print("⚠️ Google Sheets save failed:", e)

def notify_telegram(phone, message, reply):
    try:
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            text = f"📥 New Lead:\n📱 Phone: {phone}\n💬 Message: {message}\n🤖 AI Reply: {reply}"
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text})
    except Exception as e:
        print("⚠️ Telegram notification failed:", e)

# -------------------- WHATSAPP WEBHOOK --------------------
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    try:
        incoming_msg = request.values.get("Body", "").strip()
        from_number = request.values.get("From", "").replace("whatsapp:", "")

        if not incoming_msg:
            return str(MessagingResponse())

        # ✅ Generate AI response
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Thryvix AI Lead Agent. Greet warmly and guide the user to share "
                        "their name, business type, and goal. Respond naturally in their language "
                        "(English, Malayalam, or Manglish)."
                    )
                },
                {"role": "user", "content": incoming_msg}
            ]
        )
        ai_reply = response.choices[0].message.content.strip()

        # ✅ Save lead in all systems
        save_lead_to_db(from_number, incoming_msg, ai_reply)
        save_lead_to_sheets(from_number, incoming_msg, ai_reply)
        notify_telegram(from_number, incoming_msg, ai_reply)

        # ✅ Send back reply
        twilio_response = MessagingResponse()
        twilio_response.message(ai_reply)
        return str(twilio_response)

    except Exception as e:
        print("❌ WhatsApp webhook error:", e)
        traceback.print_exc()
        error_response = MessagingResponse()
        error_response.message("⚠️ Sorry, something went wrong. Please try again.")
        return str(error_response)

# -------------------- HEALTH CHECK --------------------
@app.route("/")
def home():
    return "✅ Thryvix Lead Bot is running!"

# -------------------- RUN APP --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
