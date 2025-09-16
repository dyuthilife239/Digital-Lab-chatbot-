# app.py

from flask import Flask, request, jsonify, render_template
from openai import OpenAI
import os

# Load API Key (make sure you set it in Render or local environment)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Flask app
app = Flask(__name__)

# Conversation memory
conversation_history = [
    {"role": "system", "content": 
     "You are the Digital Money Lab assistant. "
     "Your job is to explain the course clearly, give extra advice, "
     "encourage students, and always highlight the greatness of the course. "
     "Be friendly and motivational."}
]

@app.route("/")
def home():
    return render_template("index.html")  # simple chat UI

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")

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

    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)