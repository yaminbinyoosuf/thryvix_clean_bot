import os
import psycopg
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_whatsapp_followup(phone, message):
    # 🔁 Replace this with Twilio API call if you want auto WhatsApp message
    print(f"[📩 FOLLOW-UP] Would send to {phone}: {message}")

def send_telegram_alert(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        requests.post(url, json=payload)
    except Exception as e:
        print("❌ Telegram error:", e)

def check_and_send_followups():
    print("🔁 Checking for inactive leads...")
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT phone, message, created_at FROM leads
                    WHERE created_at < NOW() - INTERVAL '4 hours'
                    AND phone NOT IN (
                        SELECT phone FROM leads
                        WHERE created_at > NOW() - INTERVAL '4 hours'
                    )
                """)
                leads = cur.fetchall()

        for lead in leads:
            phone, message, created_at = lead
            follow_text = (
                "👋 Hey again! Just checking if you'd like me to prepare a quick plan for your project. "
                "Would you like to continue the conversation?"
            )
            send_whatsapp_followup(phone, follow_text)
            send_telegram_alert(f"📬 Follow-up prepared for {phone} (last seen: {created_at})")

    except Exception as e:
        print("❌ Follow-up check error:", e)

if __name__ == "__main__":
    check_and_send_followups()
