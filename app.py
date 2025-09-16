# app.py

from flask import Flask, request, jsonify, render_template
from openai import OpenAI
import os

# Initialize OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Flask app
app = Flask(__name__)

# Load course order from order.txt
def load_course_order():
    if os.path.exists("order.txt"):
        with open("order.txt", "r", encoding="utf-8") as f:
            return f.read()
    return "No course order found."

course_order = load_course_order()

# Memory (chat history per session)
conversation_history = [
    {
        "role": "system",
        "content": (
            "You are the Digital Lab chatbot. "
            "You guide students through three main courses: "
            "1) Digital Money Lab, 2) Dropshipping Mastery, 3) AI Business. "
            "Always use the official module order from 'order.txt'. "
            "When asked for study plans (like 30-day breakdowns), evenly split modules by days. "
            "Be friendly, motivational, and structured in responses."
        )
    },
    {"role": "system", "content": "Here is the official course module order:\n" + course_order}
]

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")

    # Add user message
    conversation_history.append({"role": "user", "content": user_input})

    # Ask OpenAI
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation_history
    )

    reply = response.choices[0].message.content

    # Save bot response to history
    conversation_history.append({"role": "assistant", "content": reply})

    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
