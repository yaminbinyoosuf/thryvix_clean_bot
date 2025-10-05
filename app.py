import os
import json
import smtplib
import traceback
from datetime import datetime, timedelta

from flask import Flask, request, render_template, redirect, url_for, session, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import psycopg
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from email.mime.text import MIMEText
import requests
from dotenv import load_dotenv

# -------------------- CONFIG --------------------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "supersecretkey")

# OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8343593934:AAFtczpvRvZc_c-4JwQFVcTxSJFEKSag3K8")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1129466669")

# Email
EMAIL_USER = os.getenv("EMAIL_USER", "contact.thryvixai@gmail.com")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "contact.thryvixai@gmail.com")

# Database
DATABASE_URL = os.getenv("DATABASE_URL")

# Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("thryvixleadbot-91115c548796.json", scope)
gs_client = gspread.authorize(creds)
sheet = gs_client.open("Thryvix_Leads").sheet1

# -------------------- DATABASE SETUP --------------------
def init_db():
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS leads (
                        id SERIAL PRIMARY KEY,
                        name TEXT,
                        phone TEXT,
                        language TEXT,
                        message TEXT,
                        source TEXT,
                        score INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
    except Exception as e:
        print("❌ Database init error:", e)

init_db()

# -------------------- HELPER FUNCTIONS --------------------
def save_lead_to_db(name, phone, language, message, source, score):
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO leads (name, phone, language, message, source, score)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (name, phone, language, message, source, score))
                conn.commit()
    except Exception as e:
        print("❌ Save lead error:", e)

def save_to_google_sheets(data):
    try:
        sheet.append_row(data)
    except Exception as e:
        print("❌ Google Sheets error:", e)

def send_telegram_alert(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        requests.post(url, json=payload)
    except Exception as e:
        print("❌ Telegram alert error:", e)

def send_email_alert(subject, body):
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_USER
        msg["To"] = ALERT_EMAIL

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, ALERT_EMAIL, msg.as_string())
    except Exception as e:
        print("❌ Email alert error:", e)
# -------------------- LANGUAGE DETECTION --------------------
def detect_language(text):
    text = text.lower()
    if any(ch in text for ch in "അആഇഈഉഊഎഏഐഒഓഔകഖഗഘങചഛജഝഞടഠഡഢണതഥദധനപഫബഭമയരലവശഷസഹളഴറ"):
        return "Malayalam"
    elif any(word in text for word in ["kaise", "kya", "hai", "nahi", "bana", "karo"]):
        return "Hinglish"
    elif any(word in text for word in ["entha", "undo", "alle", "ano", "venam"]):
        return "Manglish"
    else:
        return "English"

# -------------------- LEAD SCORING --------------------
def calculate_lead_score(message):
    message = message.lower()
    score = 10
    if "demo" in message or "price" in message or "how much" in message:
        score += 30
    if "book" in message or "buy" in message or "project" in message:
        score += 30
    if "urgent" in message or "asap" in message:
        score += 20
    if len(message) > 100:
        score += 10
    return min(score, 100)

# -------------------- AI REPLY GENERATOR --------------------
def generate_ai_reply(user_message, language="English"):
    try:
        system_prompt = (
            "You are ThryvixAI LeadAgent – an intelligent lead assistant that responds naturally and professionally. "
            "Use the user's language (Malayalam, Manglish, Hinglish, or English). "
            "Always guide them toward booking a demo or sharing their project details. "
            "Be polite and never end abruptly."
        )

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
        )
        return completion.choices[0].message.content.strip()

    except Exception as e:
        print("❌ AI reply error:", e)
        return "Sorry, I'm having trouble responding right now."

# -------------------- PROCESS NEW LEAD --------------------
def process_new_lead(phone, message):
    language = detect_language(message)
    score = calculate_lead_score(message)
    ai_reply = generate_ai_reply(message, language)

    # Save to DB
    save_lead_to_db(
        name=None,
        phone=phone,
        language=language,
        message=message,
        source="WhatsApp",
        score=score
    )

    # Save to Google Sheets
    save_to_google_sheets([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        phone,
        language,
        message,
        "WhatsApp",
        score
    ])

    # Send Telegram + Email Alerts
    alert_text = f"📩 New Lead\n📱 Phone: {phone}\n🗣️ Language: {language}\n💬 Message: {message}\n🔥 Score: {score}"
    send_telegram_alert(alert_text)
    send_email_alert("📩 New Lead Alert", alert_text)

    return ai_reply
# -------------------- WHATSAPP WEBHOOK --------------------
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    try:
        incoming_msg = request.values.get("Body", "").strip()
        from_number = request.values.get("From", "").replace("whatsapp:", "")

        if not incoming_msg:
            return str(MessagingResponse())

        # Generate AI reply + process lead
        ai_reply = process_new_lead(from_number, incoming_msg)

        # Build WhatsApp response
        resp = MessagingResponse()
        msg = resp.message()
        msg.body(ai_reply)
        return str(resp)

    except Exception as e:
        print("❌ WhatsApp webhook error:", e)
        traceback.print_exc()
        return str(MessagingResponse())

# -------------------- FOLLOW-UP LOGIC --------------------
def schedule_follow_up(phone, message):
    """This function is triggered after some time if lead doesn't reply."""
    try:
        follow_up_text = (
            f"Hi again 👋, just checking if you'd like me to prepare a quick plan for your project.\n"
            "Would you like to proceed with a demo or share more details?"
        )
        send_telegram_alert(f"⏱️ Follow-up sent to {phone}: {follow_up_text}")
    except Exception as e:
        print("❌ Follow-up scheduling error:", e)

# -------------------- MANUAL TEST ROUTE --------------------
@app.route("/test", methods=["GET"])
def test():
    return jsonify({"status": "ok", "message": "LeadAgent V3 is running ✅"})

# -------------------- LOGIN ROUTES --------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == os.getenv("ADMIN_USER", "admin") and password == os.getenv("ADMIN_PASS", "thryvixai@9495"):
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")
# -------------------- DASHBOARD --------------------
@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    leads = []
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM leads ORDER BY created_at DESC")
                leads = cur.fetchall()
    except Exception as e:
        print("❌ Dashboard DB error:", e)

    return render_template("dashboard.html", leads=leads)

# -------------------- EXPORT LEADS --------------------
@app.route("/export", methods=["GET"])
def export_leads():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM leads ORDER BY created_at DESC")
                rows = cur.fetchall()

        # Convert to CSV
        csv_path = "/tmp/leads_export.csv"
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("ID,Name,Phone,Language,Message,Source,Score,Created At\n")
            for row in rows:
                f.write(",".join([str(r) if r is not None else "" for r in row]) + "\n")

        return send_file(csv_path, as_attachment=True)
    except Exception as e:
        print("❌ Export error:", e)
        return "Failed to export", 500

# -------------------- LOGOUT --------------------
@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))

# -------------------- RUN APP --------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
