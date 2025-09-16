# app.py
from flask import Flask, request, jsonify, render_template
from openai import OpenAI
import os
import PyPDF2

# Load API Key (set in Render environment)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Flask app
app = Flask(__name__)

# Function to load all PDFs in the project folder
def load_all_pdfs():
    text = ""
    for file in os.listdir("."):
        if file.endswith(".pdf"):
            try:
                with open(file, "rb") as pdf_file:
                    reader = PyPDF2.PdfReader(pdf_file)
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
            except Exception as e:
                print(f"❌ Could not read {file}: {e}")
    return text

# Load all PDF course material automatically
course_text = load_all_pdfs()

# Conversation memory
conversation_history = [
    {"role": "system", "content": f"""
    You are the Digital Money Lab assistant. 
    You have access to this course material:\n\n{course_text}\n\n
    Your job is to explain the course clearly, give extra advice,
    encourage students, and always highlight the greatness of the course.
    Be friendly and motivational.
    """}
]

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")
    
    # Add user input
    conversation_history.append({"role": "user", "content": user_input})

    # Get response from OpenAI
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation_history
    )

    reply = response.choices[0].message.content

    # Add reply to memory
    conversation_history.append({"role": "assistant", "content": reply})

    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
