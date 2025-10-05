import os
import json
import traceback
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import psycopg2
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

# -------------------- Flask Setup --------------------
app = Flask(__name__)

# -------------------- OpenAI Setup --------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -------------------- Database Setup --------------------
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# -------------------- Google Sheets Setup --------------------
google_creds = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
gc = gspread.authorize(credentials)
sheet = gc.open("Thryvix Leads").sheet1  # Replace with your sheet name

# -------------------- Telegram Setup --------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# -------------------- Helper: Save Lead --------------------
def save_lead_to_db(phone, message):
    cur.execute("INSERT INTO leads (phone, message) VALUES (%s, %s)", (phone, message))
    conn.commit()

def save_lead_to_sheet(phone, message):
    sheet.append_row([phone, message])

def send_telegram_alert(phone, message):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        text = f"📢 New Lead Received!\n📱 Phone: {phone}\n💬 Message: {message}"
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text})

# -------------------- Lead Processing --------------------
def process_new_lead(phone, message):
    # Save to DB + Sheets + Telegram
    try:
        save_lead_to_db(phone, message)
        save_lead_to_sheet(phone, message)
        send_telegram_alert(phone, message)
    except Exception as e:
        print("⚠️ Lead save error:", e)

    # AI Response
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are Thryvix Lead Agent, a smart AI that engages leads, asks relevant follow-up questions, and helps qualify them."},
            {"role": "user", "content": message}
        ]
    )
    return response.choices[0].message.content

# -------------------- WhatsApp Webhook --------------------
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    try:
        incoming_msg = request.values.get("Body", "").strip()
        from_number = request.values.get("From", "").replace("whatsapp:", "")

        if not incoming_msg:
            return str(MessagingResponse())

        ai_reply = process_new_lead(from_number, incoming_msg)

        resp = MessagingResponse()
        msg = resp.message()
        msg.body(ai_reply)
        return str(resp)

    except Exception as e:
        print("❌ WhatsApp webhook error:", e)
        traceback.print_exc()
        return str(MessagingResponse())

# -------------------- Dashboard API --------------------
@app.route("/leads", methods=["GET"])
def get_leads():
    try:
        cur.execute("SELECT phone, message, created_at FROM leads ORDER BY created_at DESC")
        leads = cur.fetchall()
        return jsonify([
            {"phone": row[0], "message": row[1], "created_at": row[2].isoformat()}
            for row in leads
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------- Health Check --------------------
@app.route("/", methods=["GET"])
def home():
    return "✅ Thryvix Lead Agent is running!"

# -------------------- Main --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
