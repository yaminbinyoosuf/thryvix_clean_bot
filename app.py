import os
import json
import traceback
import logging
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import psycopg
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

# -------------------- Logging Setup --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- Flask Setup --------------------
app = Flask(__name__)

# -------------------- OpenAI Setup --------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -------------------- Database Setup --------------------
DATABASE_URL = os.getenv("DATABASE_URL")
conn_pool = None

def init_db_pool():
    global conn_pool
    try:
        conn_pool = psycopg.pool.SimpleConnectionPool(1, 20, DATABASE_URL)
        logger.info("Database connection pool initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database connection pool: {e}")
        raise

# Initialize database pool at startup
init_db_pool()

# -------------------- Google Sheets Setup --------------------
try:
    google_creds = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
    gc = gspread.authorize(credentials)
    sheet = gc.open("Thryvix Leads").sheet1  # Replace with your sheet name
except Exception as e:
    logger.error(f"Google Sheets setup error: {e}")
    raise

# -------------------- Telegram Setup --------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# -------------------- Helper: Save Lead --------------------
def save_lead_to_db(phone, message):
    conn = conn_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO leads (phone, message) VALUES (%s, %s)", (phone, message))
        conn.commit()
        logger.info(f"Saved lead to database: {phone}")
    except Exception as e:
        logger.error(f"Error saving lead to database: {e}")
        conn.rollback()
        raise
    finally:
        conn_pool.putconn(conn)

def save_lead_to_sheet(phone, message):
    try:
        sheet.append_row([phone, message])
        logger.info(f"Saved lead to Google Sheets: {phone}")
    except Exception as e:
        logger.error(f"Error saving lead to Google Sheets: {e}")
        raise

def send_telegram_alert(phone, message):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            text = f"📢 New Lead Received!\n📱 Phone: {phone}\n💬 Message: {message}"
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            response = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text})
            response.raise_for_status()
            logger.info(f"Sent Telegram alert for lead: {phone}")
        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}")
            raise

# -------------------- Lead Processing --------------------
def process_new_lead(phone, message):
    try:
        # Save to DB, Sheets, and Telegram
        save_lead_to_db(phone, message)
        save_lead_to_sheet(phone, message)
        send_telegram_alert(phone, message)
        
        # AI Response
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are Thryvix Lead Agent, a smart AI that engages leads, asks relevant follow-up questions, and helps qualify them."},
                {"role": "user", "content": message}
            ]
        )
        ai_reply = response.choices[0].message.content
        logger.info(f"Generated AI response for lead {phone}: {ai_reply}")
        return ai_reply
    except Exception as e:
        logger.error(f"Error processing lead {phone}: {e}")
        traceback.print_exc()
        return "Sorry, an error occurred while processing your message. Please try again later."

# -------------------- WhatsApp Webhook --------------------
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    try:
        incoming_msg = request.values.get("Body", "").strip()
        from_number = request.values.get("From", "").replace("whatsapp:", "")
        
        if not incoming_msg:
            logger.warning("Received empty message in WhatsApp webhook")
            return str(MessagingResponse())

        ai_reply = process_new_lead(from_number, incoming_msg)
        
        resp = MessagingResponse()
        msg = resp.message()
        msg.body(ai_reply)
        logger.info(f"Sent WhatsApp response to {from_number}: {ai_reply}")
        return str(resp)
    except Exception as e:
        logger.error(f"WhatsApp webhook error: {e}")
        traceback.print_exc()
        resp = MessagingResponse()
        msg = resp.message()
        msg.body("Sorry, an error occurred. Please try again later.")
        return str(resp)

# -------------------- Dashboard API --------------------
@app.route("/leads", methods=["GET"])
def get_leads():
    conn = conn_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT phone, message, created_at FROM leads ORDER BY created_at DESC")
        leads = cur.fetchall()
        return jsonify([
            {"phone": row[0], "message": row[1], "created_at": row[2].isoformat()}
            for row in leads
        ])
    except Exception as e:
        logger.error(f"Error fetching leads: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn_pool.putconn(conn)

# -------------------- Health Check --------------------
@app.route("/", methods=["GET"])
def home():
    return "✅ Thryvix Lead Agent is running!"

# -------------------- Main --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))