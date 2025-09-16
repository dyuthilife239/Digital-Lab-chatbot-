# app.py
from flask import Flask, request, jsonify, render_template, session
from flask_session import Session
from openai import OpenAI
import os, fitz

# Load API Key
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecret")
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# ---- PDF LOADING ----
COURSE_FOLDER = "."
course_texts = {}

def load_pdfs():
    global course_texts
    course_texts = {}
    for file in os.listdir(COURSE_FOLDER):
        if file.endswith(".pdf"):
            try:
                doc = fitz.open(os.path.join(COURSE_FOLDER, file))
                text = ""
                for page in doc:
                    text += page.get_text("text")
                course_texts[file] = text
            except Exception as e:
                print(f"Error loading {file}: {e}")

load_pdfs()

# ---- Routes ----
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")

    # Init session
    if "history" not in session:
        session["history"] = [
            {"role": "system", "content": "You are a course assistant. Use only the uploaded course PDFs to answer."}
        ]

    # Add context from PDFs
    context = "\n\n".join([f"{k}:\n{v[:1500]}" for k, v in course_texts.items()])

    session["history"].append({"role": "user", "content": f"{user_input}\n\nReference material:\n{context}"})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=session["history"]
    )

    reply = response.choices[0].message.content
    session["history"].append({"role": "assistant", "content": reply})

    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
