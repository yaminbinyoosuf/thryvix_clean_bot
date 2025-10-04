import os
import json
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, session
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import psycopg
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ------------------ CONFIG ------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "supersecretkey")

# OpenAI Client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Database URL
DATABASE_URL = os.getenv("DATABASE_URL")

# Optional DB connection
def get_db_connection():
    try:
        conn = psycopg.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print("⚠️ Database connection failed:", e)
        return None

# ------------------ GOOGLE SHEETS ------------------
def connect_gsheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("thryvixleadbot-91115c548796.json", scope)
        client = gspread.authorize(creds)
        return client.open("Thryvix_Leads").sheet1
    except Exception as e:
        print("⚠️ Google Sheets connection failed:", e)
        return None

sheet = connect_gsheet()

# ------------------ AI RESPONSE ------------------
def generate_ai_reply(user_message, language="english"):
    system_prompt = "You are Thryvix AI assistant. Reply smartly and help convert leads into clients. Use simple, conversational tone."
    if language.lower() == "malayalam":
        system_prompt += " Reply in Malayalam (you can use Manglish if user uses it)."
    elif language.lower() == "hinglish":
        system_prompt += " Reply in Hinglish (mix of Hindi and English)."

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        temperature=0.7
    )
    return completion.choices[0].message.content.strip()

# ------------------ LEAD SCORING ------------------
def calculate_lead_score(message):
    keywords = ["price", "cost", "demo", "book", "buy", "details", "interested"]
    score = sum(10 for word in keywords if word in message.lower())
    return min(score, 100)

# ------------------ SAVE LEAD ------------------
def save_lead(phone, message, language, score):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS leads (
                        id SERIAL PRIMARY KEY,
                        phone TEXT,
                        message TEXT,
                        language TEXT,
                        score INT,
                        created_at TIMESTAMP
                    )
                """)
                cur.execute(
                    "INSERT INTO leads (phone, message, language, score, created_at) VALUES (%s, %s, %s, %s, %s)",
                    (phone, message, language, score, now)
                )
                conn.commit()
        except Exception as e:
            print("⚠️ Database insert failed:", e)
        finally:
            conn.close()

    if sheet:
        try:
            sheet.append_row([phone, message, language, score, now])
        except Exception as e:
            print("⚠️ Google Sheets append failed:", e)

# ------------------ WHATSAPP BOT ------------------
@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "").replace("whatsapp:", "")

    # Detect language (simple heuristic)
    if any(x in incoming_msg for x in ["എന്ത്", "വില", "പേര്"]):
        language = "malayalam"
    elif any(x in incoming_msg for x in ["hai", "kya", "bhai", "acha"]):
        language = "hinglish"
    else:
        language = "english"

    score = calculate_lead_score(incoming_msg)
    ai_reply = generate_ai_reply(incoming_msg, language)
    save_lead(from_number, incoming_msg, language, score)

    resp = MessagingResponse()
    resp.message(ai_reply)
    return str(resp)
import io
import csv
from flask import send_file

# ------------------ AUTH ------------------
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASS = os.getenv("ADMIN_PASS")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == ADMIN_USER and password == ADMIN_PASS:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))

# ------------------ DASHBOARD ------------------
@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    conn = get_db_connection()
    leads = []
    total = 0
    mal = hin = eng = 0

    if conn:
        with conn.cursor() as cur:
            cur.execute("SELECT phone, message, language, score, created_at FROM leads ORDER BY created_at DESC")
            leads = cur.fetchall()
            total = len(leads)
            for l in leads:
                if l[2] == "malayalam":
                    mal += 1
                elif l[2] == "hinglish":
                    hin += 1
                else:
                    eng += 1
        conn.close()

    stats = {
        "total": total,
        "malayalam": mal,
        "hinglish": hin,
        "english": eng
    }

    return render_template("dashboard.html", leads=leads, stats=stats)

# ------------------ CSV EXPORT ------------------
@app.route("/export")
def export_csv():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    conn = get_db_connection()
    if not conn:
        return "Database unavailable", 500

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Phone", "Message", "Language", "Score", "Created At"])

    with conn.cursor() as cur:
        cur.execute("SELECT phone, message, language, score, created_at FROM leads ORDER BY created_at DESC")
        for row in cur.fetchall():
            writer.writerow(row)

    output.seek(0)
    conn.close()

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='thryvix_leads.csv'
    )

# ------------------ RUN APP ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
