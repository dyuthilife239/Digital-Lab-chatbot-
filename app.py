# app.py
import os, io, sqlite3, fitz, csv
from datetime import datetime
from flask import (
    Flask, request, jsonify, render_template, session, send_file, g
)
from flask_session import Session
from openai import OpenAI

# ---------- CONFIG ----------
DATABASE = "data.db"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Env variables
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SECRET_KEY = os.environ.get("SECRET_KEY", "supersecret")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---------- APP ----------
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_TYPE"] = "filesystem"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
Session(app)

# ---------- DB helpers ----------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    c = db.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY,
      username TEXT,
      created_at TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS chats (
      id INTEGER PRIMARY KEY,
      user_id INTEGER,
      role TEXT,
      content TEXT,
      created_at TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS analytics (
      id INTEGER PRIMARY KEY,
      user_id INTEGER,
      question TEXT,
      answer TEXT,
      created_at TEXT
    )""")
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

with app.app_context():
    init_db()

# ---------- Load PDFs + order.txt ----------
def load_all_pdfs_text():
    result = {}
    for fname in os.listdir("."):
        if fname.lower().endswith(".pdf"):
            try:
                doc = fitz.open(fname)
                txt = ""
                for p in doc:
                    txt += p.get_text("text") + "\n"
                result[fname] = txt
            except Exception as e:
                print("PDF read error", fname, e)
    order_text = ""
    if os.path.exists("order.txt"):
        with open("order.txt", "r", encoding="utf-8") as f:
            order_text = f.read()
    return result, order_text

course_texts, course_order_text = load_all_pdfs_text()

# ---------- System Prompt ----------
SYSTEM_PROMPT = f"""
You are the Digital Money Lab Mentor & Motivator.
Be warm, friendly, motivating and practical.
Use simple language and step-by-step advice.
Use the course PDFs and the official module order for accuracy.
You may add external strategies if useful, but always tie them back to the course.
If an image or file is uploaded, analyze and give practical feedback.
"""

# ---------- Helpers ----------
def user_id_from_session():
    if "user_id" not in session:
        db = get_db()
        c = db.cursor()
        now = datetime.utcnow().isoformat()
        c.execute("INSERT INTO users (username, created_at) VALUES (?, ?)", (f"user_{now}", now))
        db.commit()
        session["user_id"] = c.lastrowid
    return session["user_id"]

def append_chat(user_id, role, content):
    db = get_db()
    c = db.cursor()
    c.execute("INSERT INTO chats (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
              (user_id, role, content, datetime.utcnow().isoformat()))
    db.commit()

def log_analytics(user_id, question, answer):
    db = get_db()
    c = db.cursor()
    c.execute("INSERT INTO analytics (user_id, question, answer, created_at) VALUES (?, ?, ?, ?)",
              (user_id, question, answer, datetime.utcnow().isoformat()))
    db.commit()

# ---------- Routes ----------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message", "").strip()
    user_id = user_id_from_session()

    # Build context
    context_parts = []
    if course_order_text:
        context_parts.append("COURSE ORDER:\n" + course_order_text)
    for fname, txt in course_texts.items():
        context_parts.append(f"FILE: {fname}\n{txt[:3000]}")
    context = "\n\n".join(context_parts)[:15000]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": "Course context:\n" + context}
    ]

    # Recent chat history
    db = get_db()
    c = db.cursor()
    c.execute("SELECT role, content FROM chats WHERE user_id = ? ORDER BY id DESC LIMIT 12", (user_id,))
    rows = c.fetchall()
    for r in reversed(rows):
        messages.append({"role": r["role"], "content": r["content"]})

    # Current message
    messages.append({"role": "user", "content": message})

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
        max_tokens=700
    )
    reply = resp.choices[0].message.content

    append_chat(user_id, "user", message)
    append_chat(user_id, "assistant", reply)
    log_analytics(user_id, message, reply)

    return jsonify({"reply": reply})

@app.route("/upload-image", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({"reply": "No image uploaded"}), 400
    f = request.files["image"]
    path = os.path.join(app.config["UPLOAD_FOLDER"], f.filename)
    f.save(path)

    user_id = user_id_from_session()
    prompt = f"I uploaded an image named {f.filename}. Please analyze it and explain how it relates to the course."
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=600
    )
    reply = resp.choices[0].message.content

    append_chat(user_id, "user", f"[IMAGE] {f.filename}")
    append_chat(user_id, "assistant", reply)
    log_analytics(user_id, f"[IMAGE] {f.filename}", reply)

    return jsonify({"reply": reply})

@app.route("/upload-file", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    f = request.files["file"]
    fname = f.filename
    dest = os.path.join(app.config["UPLOAD_FOLDER"], fname)
    f.save(dest)
    user_id = user_id_from_session()

    reply = "File uploaded. Currently, only PDFs and images can be analyzed."
    if fname.lower().endswith(".pdf"):
        try:
            doc = fitz.open(dest)
            text = ""
            for p in doc:
                text += p.get_text("text")[:4000]
            prompt = f"A student uploaded this PDF:\n{text}\n\nGive feedback and 3 improvement tips relevant to the course."
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500
            )
            reply = resp.choices[0].message.content
        except:
            reply = "Could not read PDF content."

    append_chat(user_id, "user", f"[FILE] {fname}")
    append_chat(user_id, "assistant", reply)
    log_analytics(user_id, f"[UPLOAD] {fname}", reply)

    return jsonify({"reply": reply})

@app.route("/quiz", methods=["POST"])
def quiz():
    data = request.json
    topic = data.get("topic", "")
    length = int(data.get("length", 5))
    user_id = user_id_from_session()

    prompt = f"Create {length} multiple-choice questions (4 options + answer) about: {topic}, based on course content."
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=600
    )
    quiz_text = resp.choices[0].message.content
    append_chat(user_id, "assistant", f"[QUIZ] {topic}")
    return jsonify({"quiz": quiz_text})

@app.route("/analytics")
def analytics():
    token = request.args.get("token")
    if token != SECRET_KEY:
        return "Unauthorized", 401
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM analytics ORDER BY created_at DESC LIMIT 1000")
    rows = c.fetchall()
    proxy = io.StringIO()
    writer = csv.writer(proxy)
    writer.writerow(["id","user_id","question","answer","created_at"])
    for r in rows:
        writer.writerow([r["id"], r["user_id"], r["question"], r["answer"], r["created_at"]])
    mem = io.BytesIO()
    mem.write(proxy.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="analytics.csv", mimetype="text/csv")

@app.route("/download-transcript")
def download_transcript():
    user_id = user_id_from_session()
    db = get_db()
    c = db.cursor()
    c.execute("SELECT role, content, created_at FROM chats WHERE user_id = ? ORDER BY id", (user_id,))
    rows = c.fetchall()
    txt = ""
    for r in rows:
        txt += f"{r['created_at']} | {r['role'].upper()}:\n{r['content']}\n\n"
    mem = io.BytesIO()
    mem.write(txt.encode("utf-8"))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="transcript.txt", mimetype="text/plain")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
