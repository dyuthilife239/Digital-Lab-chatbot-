# app.py

from flask import Flask, request, jsonify, render_template, session
from openai import OpenAI
import os
from flask_session import Session

# Load API Key from Render environment
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")  # needed for sessions

# Configure server-side session storage
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

@app.route("/")
def home():
    # Initialize session memory if new student
    if "conversation_history" not in session:
        session["conversation_history"] = [
            {"role": "system", "content": 
             "You are the Digital Money Lab assistant. "
             "Your job is to explain the course clearly, give extra advice, "
             "encourage students, and always highlight the greatness of the course. "
             "Be friendly and motivational."}
        ]
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")

    # Get student-specific memory
    conversation_history = session.get("conversation_history", [])

    # Add user message
    conversation_history.append({"role": "user", "content": user_input})

    # Get response from OpenAI
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation_history
    )

    reply = response.choices[0].message.content

    # Add bot reply to memory
    conversation_history.append({"role": "assistant", "content": reply})

    # Save back to session
    session["conversation_history"] = conversation_history

    return jsonify({"reply": reply})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
