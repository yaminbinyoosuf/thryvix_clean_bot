from flask import Flask, request, jsonify
import psycopg2
from twilio.twiml.messaging_response import MessagingResponse
import openai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import telegram
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
import uuid
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)

# Load environment variables
load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
DATABASE_URL = os.getenv("DATABASE_URL")
GOOGLE_CREDS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# Initialize OpenAI
openai.api_key = OPENAI_API_KEY

# Initialize Telegram bot
telegram_bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)

# Initialize Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS, scope)
client = gspread.authorize(creds)
sheet = client.open("Thryvix_Leads").sheet1

# Database connection
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# Create leads table if not exists
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id UUID PRIMARY KEY,
            name VARCHAR(255),
            phone_number VARCHAR(20),
            message TEXT,
            status VARCHAR(50),
            created_at TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# Save lead to database
def save_lead(name, phone_number, message, status="new"):
    conn = get_db_connection()
    cur = conn.cursor()
    lead_id = str(uuid.uuid4())
    created_at = datetime.utcnow()
    cur.execute(
        "INSERT INTO leads (id, name, phone_number, message, status, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (lead_id, name, phone_number, message, status, created_at)
    )
    conn.commit()
    cur.close()
    conn.close()
    return lead_id

# Save lead to Google Sheets
def save_to_google_sheets(name, phone_number, message, status, created_at):
    row = [str(created_at), name, phone_number, message, status]
    sheet.append_row(row)

# Send Telegram notification
async def send_telegram_notification(name, phone_number, message):
    text = f"New Lead!\nName: {name}\nPhone: {phone_number}\nMessage: {message}"
    await telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)

# Send email notification
def send_email_notification(name, phone_number, message):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "New Lead from Thryvix LeadAgent"
    body = f"New Lead!\n\nName: {name}\nPhone: {phone_number}\nMessage: {message}"
    msg.attach(MIMEText(body, 'plain'))
    
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(EMAIL_USER, EMAIL_PASS)
    server.send_message(msg)
    server.quit()

# Generate AI-powered response
def generate_ai_response(message, phone_number):
    prompt = f"""
    You are Thryvix LeadAgent, a professional lead generation bot. A user with phone number {phone_number} sent: "{message}".
    - If this is a new conversation, greet them warmly and ask for their name and what service they are interested in.
    - If they provide a name or service, ask follow-up questions to qualify the lead (e.g., budget, timeline).
    - If they stop responding, suggest a follow-up.
    - Keep responses concise, friendly, and professional.
    """
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": message}
        ],
        max_tokens=150
    )
    return response.choices[0].message.content.strip()

# WhatsApp webhook endpoint
@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    phone_number = request.values.get('From', '').replace('whatsapp:', '')
    
    # Generate AI response
    ai_response = generate_ai_response(incoming_msg, phone_number)
    
    # Save lead to database
    name = "Unknown"  # Update logic to extract name from AI response or message
    status = "new"
    lead_id = save_lead(name, phone_number, incoming_msg, status)
    
    # Save to Google Sheets
    save_to_google_sheets(name, phone_number, incoming_msg, status, datetime.utcnow())
    
    # Send notifications
    import asyncio
    asyncio.run(send_telegram_notification(name, phone_number, incoming_msg))
    send_email_notification(name, phone_number, incoming_msg)
    
    # Respond to user
    resp = MessagingResponse()
    resp.message(ai_response)
    return str(resp)

# Health check endpoint
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))