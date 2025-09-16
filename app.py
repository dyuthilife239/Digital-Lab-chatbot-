# app.py

from flask import Flask, request, jsonify, render_template, session, send_file
from openai import OpenAI
import os
from flask_session import Session
import fitz  # PyMuPDF
import csv
from datetime import datetime

# Load API Key from Render environment
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")

# Configure server-side session storage
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# ✅ Load and extract text from course PDFs
def load_course_material(pdf_files):
    course_text = ""
    for pdf in pdf_files:
        if os.path.exists(pdf):
            doc = fitz.open(pdf)
            for page in doc:
                course_text += page.get_text()
    return course_text

# Put your actual PDF filenames here (upload them into repo root)
course_text = load_course_material(["course1.pdf", "course2.pdf", "course3.pdf"])

# ✅ Analytics logging
def log_interaction(user_input, bot_reply):
    with open("analytics.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(), user_input, bot_reply])

@app.route("/")
def home():
    # Initialize memory per student session
    if "conversation_history" not in session:
        session["conversation_history"] = [
            {"role": "system", "content": 
             f"You are the Digital Money Lab assistant. "
             f"Use the following course material as your main knowledge base:\n{course_text}\n\n"
             "Always explain clearly, motivate students, and highlight the greatness of the course."}
        ]
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")

    conversation_history = session.get("conversation_history", [])

    # Add user input
    conversation_history.append({"role": "user", "content": user_input})

    # Get reply from OpenAI
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation_history
    )

    reply = response.choices[0].message.content

    # Add bot reply
    conversation_history.append({"role": "assistant", "content": reply})
    session["conversation_history"] = conversation_history

    # ✅ Log analytics
    log_interaction(user_input, reply)

    return jsonify({"reply": reply})

# ✅ New route to download analytics
@app.route("/analytics")
def download_analytics():
    if os.path.exists("analytics.csv"):
        return send_file("analytics.csv", as_attachment=True)
    else:
        return "No analytics data yet.", 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
