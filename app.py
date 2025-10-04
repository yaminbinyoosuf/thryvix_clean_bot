import os
import json
import traceback
from datetime import datetime, timedelta

from flask import Flask, request, render_template, redirect, url_for, session, send_file
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import psycopg2
import psycopg2.extras
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import smtplib
from email.mime.text import MIMEText
import requests

# ------------------ CONFIG ------------------

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "supersecretkey")

# OpenAI setup
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Email Alerts
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
ALERT_EMAIL = os.getenv("ALERT_EMAIL")

# Google Sheets
GOOGLE_SERVICE_JSON = os.getenv("GOOGLE_SERVICE_JSON")
SHEET_NAME = "Thryvix_Leads"

# Postgres
DATABASE_URL = os.getenv("DATABASE_URL")

# Lead alert threshold
LEAD_ALERT_THRESHOLD = int(os.getenv("LEAD_ALERT_THRESHOLD", 70))

# ------------------ DATABASE INIT ------------------

def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                wa_from TEXT UNIQUE,
                language TEXT,
                business_type TEXT,
                city TEXT,
                score INT,
                last_msg_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT now()
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                wa_from TEXT,
                role TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT now()
            );
            """)
            conn.commit()

init_db()

# ------------------ GOOGLE SHEETS SETUP ------------------

def get_sheet():
    creds_json = json.loads(GOOGLE_SERVICE_JSON)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client_gs = gspread.authorize(creds)
    return client_gs.open(SHEET_NAME).sheet1

# ------------------ TELEGRAM ALERT ------------------

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text})
    except:
        pass

# ------------------ EMAIL ALERT ------------------

def send_email_alert(subject, body):
    if not SENDER_EMAIL or not SENDER_PASSWORD or not ALERT_EMAIL:
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = ALERT_EMAIL

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, ALERT_EMAIL, msg.as_string())
    except Exception as e:
        print("Email error:", e)

# ------------------ LANGUAGE SELECTION ------------------

def get_user_language(wa_from):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT language FROM leads WHERE wa_from=%s", (wa_from,))
            row = cur.fetchone()
            return row["language"] if row else None

def set_user_language(wa_from, lang):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO leads (wa_from, language, last_msg_at)
                VALUES (%s, %s, now())
                ON CONFLICT (wa_from) DO UPDATE SET language=%s, last_msg_at=now();
            """, (wa_from, lang, lang))
            conn.commit()

# ------------------ TWILIO WEBHOOK ------------------

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = (request.values.get("Body") or "").strip()
    wa_from = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    # Step 1: Language selection if not set
    user_lang = get_user_language(wa_from)
    if not user_lang:
        if "malayalam" in incoming_msg.lower() or "മലയാളം" in incoming_msg:
            set_user_language(wa_from, "ml")
            msg.body("✅ ഭാഷയായി മലയാളം തിരഞ്ഞെടുക്കപ്പെട്ടു. ഇപ്പോൾ തുടങ്ങാം! 📍 ആദ്യം പറയാമോ – താങ്കളുടെ ബിസിനസ് തരം എന്താണ്?")
            return str(resp)
        elif "english" in incoming_msg.lower():
            set_user_language(wa_from, "en")
            msg.body("✅ English selected. Let's get started! 📍 First, could you tell me what type of business you run?")
            return str(resp)
        else:
            msg.body("🌐 Please choose your language:\n\n🇮🇳 Malayalam\n🇬🇧 English\n\nദയവായി ഭാഷ തിരഞ്ഞെടുക്കൂ:")
            return str(resp)

    # If language already set, move to AI handling (Part 2)
    return handle_conversation(wa_from, incoming_msg, user_lang)
# ------------------ AI + CONVERSATION HANDLER ------------------

def get_openai_reply(messages):
    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.7
        )
        return completion.choices[0].message.content
    except Exception as e:
        print("OpenAI error:", e)
        return None

def calculate_lead_score(text):
    text_lower = text.lower()
    score = 0
    if any(word in text_lower for word in ["clinic", "hospital", "store", "service", "agency", "restaurant", "company", "business", "firm", "shop", "agency", "studio"]):
        score += 30
    if any(word in text_lower for word in ["kochi", "malappuram", "thrissur", "kollam", "kerala", "calicut", "ernakulam", "trivandrum"]):
        score += 30
    if any(word in text_lower for word in ["demo", "price", "cost", "setup", "trial", "book"]):
        score += 30
    if any(word in text_lower for word in ["urgent", "asap", "today", "now", "ഇപ്പോൾ", "ഇന്ന്"]):
        score += 10
    return min(score, 100)

def save_lead_to_db(wa_from, business_type, city, score):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO leads (wa_from, business_type, city, score, last_msg_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (wa_from) DO UPDATE
                SET business_type = COALESCE(EXCLUDED.business_type, leads.business_type),
                    city = COALESCE(EXCLUDED.city, leads.city),
                    score = COALESCE(EXCLUDED.score, leads.score),
                    last_msg_at = now();
            """, (wa_from, business_type, city, score))
            conn.commit()

def save_message(wa_from, role, content):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO messages (wa_from, role, content) VALUES (%s, %s, %s)
            """, (wa_from, role, content))
            conn.commit()

def sync_to_sheets(wa_from, business_type, city, score, language):
    try:
        sheet = get_sheet()
        sheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            wa_from,
            business_type or "",
            city or "",
            score,
            language
        ])
    except Exception as e:
        print("Sheets sync error:", e)

# ------------------ MAIN CONVERSATION ------------------

def handle_conversation(wa_from, incoming_msg, lang):
    resp = MessagingResponse()
    msg = resp.message()

    # Store incoming message
    save_message(wa_from, "user", incoming_msg)

    # Calculate lead score
    score = calculate_lead_score(incoming_msg)

    # Basic entity extraction (simple demo)
    business_type = None
    for word in ["clinic", "hospital", "store", "service", "agency", "restaurant", "company", "business", "firm", "shop", "agency", "studio"]:
        if word in incoming_msg.lower():
            business_type = word
            break

    city = None
    for c in ["kochi", "malappuram", "thrissur", "kollam", "kerala", "calicut", "ernakulam", "trivandrum"]:
        if c in incoming_msg.lower():
            city = c
            break

    save_lead_to_db(wa_from, business_type, city, score)
    sync_to_sheets(wa_from, business_type, city, score, lang)

    # Build AI prompt
    if lang == "ml":
        system_msg = "നിങ്ങൾ ഒരു ബിസിനസ് ഓട്ടോമേഷൻ അസിസ്റ്റന്റാണ്. നിങ്ങൾക്കുള്ള ലക്ഷ്യം ലീഡിനെ ഡെമോ ബുക്ക് ചെയ്യാൻ പ്രോത്സാഹിപ്പിക്കലാണ്. ചുരുക്കത്തിൽ സംസാരിക്കുക."
    else:
        system_msg = "You are a business automation assistant. Your goal is to convert leads and guide them to book a demo. Keep it concise and persuasive."

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": incoming_msg}
    ]

    ai_reply = get_openai_reply(messages)

    if not ai_reply:
        ai_reply = "Sorry, I faced a small issue. Could you tell me a bit more about your business?"

    # Save assistant reply
    save_message(wa_from, "assistant", ai_reply)

    # Alert if hot lead
    if score >= LEAD_ALERT_THRESHOLD:
        alert_text = f"🔥 HOT Lead!\n📞 {wa_from}\n🏢 {business_type or 'Unknown'}\n📍 {city or 'Unknown'}\n📊 Score: {score}"
        send_telegram(alert_text)
        send_email_alert("🔥 New Hot Lead", alert_text)

    msg.body(ai_reply)
    return str(resp)

# ------------------ FOLLOW-UP CRON ------------------

@app.route("/followup", methods=["GET"])
def followup_task():
    cutoff = datetime.now() - timedelta(hours=2)
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT wa_from, language FROM leads
                WHERE last_msg_at < %s
            """, (cutoff,))
            leads = cur.fetchall()

    for lead in leads:
        lang = lead["language"]
        if lang == "ml":
            follow_text = "ഹായ് 👋 ഇനി ഡെമോ ബുക്ക് ചെയ്യാൻ താൽപ്പര്യമുണ്ടോ?"
        else:
            follow_text = "Hi 👋 Are you still interested in booking a free demo?"

        # send via Twilio REST API (placeholder for production)
        print(f"Follow-up to {lead['wa_from']}: {follow_text}")

    return "Follow-ups checked", 200

# ------------------ DASHBOARD ------------------

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == "admin" and password == "thryvixai@9495":
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Invalid credentials")

    if not session.get("logged_in"):
        return render_template("login.html")

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM leads ORDER BY created_at DESC;")
            leads = cur.fetchall()

    return render_template("dashboard.html", leads=leads)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("dashboard"))

@app.route("/")
def home():
    return "✅ Thryvix Lead Bot is running!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
