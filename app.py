# app.py

from flask import Flask, request, jsonify, render_template
from openai import OpenAI
import os
import PyPDF2

# Load API Key (from Render environment or local .env)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Flask app
app = Flask(__name__)

# ----------- Load and Read All PDFs ------------
pdf_folder = "./"
course_text = ""

for filename in os.listdir(pdf_folder):
    if filename.endswith(".pdf"):
        with open(os.path.join(pdf_folder, filename), "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                course_text += page.extract_text() + "\n"

# ----------- Conversation Memory ------------
conversation_history = [
    {
        "role": "system",
        "content": f"""
        You are the **Digital Money Lab Mentor & Motivator**.
        - Speak like a supportive coach: warm, engaging, motivational.
        - Always explain using examples from the course PDFs (below).
        - Give **extra external knowledge or strategies** when it helps,
          but always connect it back to the student’s course journey.
        - Highlight the greatness of the course and boost student confidence.
        - Be friendly, simple, and human-like. Encourage them to take action.

        --- COURSE CONTENT START ---
        {course_text}
        --- COURSE CONTENT END ---
        """
    }
]

# ----------- Routes ------------
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
        messages=conversation_history,
        temperature=0.8,   # makes it more creative + motivational
        max_tokens=500     # longer, detailed responses
    )

    reply = response.choices[0].message.content

    # Add bot reply to memory
    conversation_history.append({"role": "assistant", "content": reply})

    return jsonify({"reply": reply})

# ----------- Run ------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
