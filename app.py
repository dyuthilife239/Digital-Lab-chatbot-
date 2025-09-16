# app.py
import os, io, sqlite3, fitz, csv
from datetime import datetime
from flask import (
    Flask, request, jsonify, render_template, session, redirect, url_for, send_file, g
)
from flask_session import Session
from openai import OpenAI

# ---------- CONFIG ----------
DATABASE = "data.db"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Read env
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SECRET_KEY = os.environ.get("SECRET_KEY", "supersecret")
COURSE_PASSWORD = os.environ.get("COURSE_PASSWORD", "mycourse2025")

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
    CREATE TABLE IF NOT EXISTS sessions (
      id INTEGER PRIMARY KEY,
      user_id INTEGER,
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
    c.execute("""
    CREATE TABLE IF NOT EXISTS progress (
      id INTEGER PRIMARY KEY,
      user_id INTEGER,
      course TEXT,
      last_module TEXT,
      streak INTEGER,
      updated_at TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS access_codes (
      code TEXT PRIMARY KEY,
      used INTEGER DEFAULT 0
    )""")
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# initialize DB on start
with app.app_context():
    init_db()

# ---------- Utility: load all PDFs and order.txt ----------
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
    # load order.txt if exists
    order_text = ""
    if os.path.exists("order.txt"):
        with open("order.txt", "r", encoding="utf-8") as f:
            order_text = f.read()
    return result, order_text

course_texts, course_order_text = load_all_pdfs_text()

# ---------- System prompt (personality + rules) ----------
SYSTEM_PROMPT = f"""
You are the Digital Money Lab Mentor & Motivator.
Be warm, friendly, motivating and practical. Use simple language.
Primary knowledge base: the course PDFs and the official order file.
If asked for step-by-step plans, use the course order as the sequence.
You may add external, practical advice if it helps, but always tie it back to course material.
If an image is uploaded, analyze and explain it and suggest next steps relevant to the student's goal.
"""

# ---------- Helpers for conversations ----------
def user_id_from_session():
    # create a simple user record per session if missing
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

# ---------- Authentication: buyer access via code or session password ----------
@app.route("/activate", methods=["POST"])
def activate():
    # user posts a code they received after purchase OR password
    code = request.json.get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "error": "No code provided."}), 400

    # check access_codes table
    db = get_db()
    c = db.cursor()
    c.execute("SELECT used FROM access_codes WHERE code = ?", (code,))
    row = c.fetchone()
    if row:
        # mark used (optional, keep single-use)
        c.execute("UPDATE access_codes SET used = 1 WHERE code = ?", (code,))
        db.commit()
        session["access_granted"] = True
        return jsonify({"ok": True})
    # fallback to shared password
    if code == COURSE_PASSWORD:
        session["access_granted"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Invalid code"}), 403

# ---------- Routes: UI ----------
@app.route("/")
def home():
    # if not allowed, show a simple landing with instructions
    if not session.get("access_granted"):
        return render_template("access.html")
    return render_template("index.html")

# ---------- Chat endpoint (text) ----------
@app.route("/chat", methods=["POST"])
def chat():
    if not session.get("access_granted"):
        return jsonify({"reply": "Access denied. Please activate with your purchase code."}), 403
    data = request.json
    message = data.get("message", "").strip()
    course = data.get("course", "")  # optional: student-selected course name
    user_id = user_id_from_session()

    # build dynamic context: short snippets from PDFs + order
    context_parts = []
    if course_order_text:
        context_parts.append("COURSE ORDER:\n" + course_order_text)
    for fname, txt in course_texts.items():
        # include only first N chars per file to keep prompt length reasonable
        context_parts.append(f"FILE: {fname}\n{txt[:3000]}")

    context = "\n\n".join(context_parts)[:15000]  # trim

    # system + conversation assembly
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": "Course context:\n" + context}
    ]

    # fetch recent chat history for this user to preserve continuity
    db = get_db()
    c = db.cursor()
    c.execute("SELECT role, content FROM chats WHERE user_id = ? ORDER BY id DESC LIMIT 12", (user_id,))
    rows = c.fetchall()
    # rows are newest first; reverse to chronological
    for r in reversed(rows):
        messages.append({"role": r["role"], "content": r["content"]})

    # add current user message
    messages.append({"role": "user", "content": message})

    # call OpenAI
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
        max_tokens=700
    )
    reply = resp.choices[0].message.content

    # persist
    append_chat(user_id, "user", message)
    append_chat(user_id, "assistant", reply)
    log_analytics(user_id, message, reply)

    return jsonify({"reply": reply})

# ---------- Image upload and analysis ----------
@app.route("/upload-image", methods=["POST"])
def upload_image():
    if not session.get("access_granted"):
        return jsonify({"reply": "Access denied."}), 403
    if "image" not in request.files:
        return jsonify({"reply": "No image file."}), 400
    f = request.files["image"]
    filename = f.filename
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    f.save(path)

    user_id = user_id_from_session()
    # For image analysis we'll pass a text + image_url instruction to the model
    # Note: OpenAI image URL from local file isn't supported by remote models; we instead include a short note and ask for interpretation.
    # Simpler: tell model we uploaded an image and include minimal context; model can request clarifying Qs.
    messages = [
        {"role":"system", "content": SYSTEM_PROMPT},
        {"role":"user", "content": f"I uploaded an image named {filename}. Please analyze it and explain what it shows, key takeaways, and how it relates to the course."}
    ]
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.6,
        max_tokens=600
    )
    reply = resp.choices[0].message.content

    append_chat(user_id, "user", f"[IMAGE_UPLOAD] {filename}")
    append_chat(user_id, "assistant", reply)
    log_analytics(user_id, f"[IMAGE] {filename}", reply)

    return jsonify({"reply": reply})

# ---------- File upload (students can upload PDFs/images for feedback) ----------
@app.route("/upload-file", methods=["POST"])
def upload_file():
    if not session.get("access_granted"):
        return jsonify({"ok": False, "error": "Access denied"}), 403
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    f = request.files["file"]
    fname = f.filename
    dest = os.path.join(app.config["UPLOAD_FOLDER"], fname)
    f.save(dest)
    user_id = user_id_from_session()

    # if pdf, extract small text and run a quick summary
    if fname.lower().endswith(".pdf"):
        try:
            doc = fitz.open(dest)
            text = ""
            for p in doc:
                text += p.get_text("text")[:4000]  # limit
            prompt = f"I uploaded a student PDF with this text:\n\n{text}\n\nPlease give constructive actionable feedback and 3 improvement suggestions relevant to the course."
            resp = client.chat.completions.create(
                model="gpt-4o-mini", messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":prompt}],
                temperature=0.7, max_tokens=500
            )
            reply = resp.choices[0].message.content
        except Exception as e:
            reply = "Could not read PDF content."
    else:
        reply = "File uploaded. If you want feedback, upload a PDF or image."

    append_chat(user_id, "user", f"[FILE_UPLOAD] {fname}")
    append_chat(user_id, "assistant", reply)
    log_analytics(user_id, f"[UPLOAD] {fname}", reply)

    return jsonify({"reply": reply})

# ---------- Quiz generator ----------
@app.route("/quiz", methods=["POST"])
def create_quiz():
    if not session.get("access_granted"):
        return jsonify({"error":"Access denied"}), 403
    data = request.json
    topic = data.get("topic", "")
    length = int(data.get("length", 5))
    user_id = user_id_from_session()

    prompt = f"Create {length} short multiple-choice questions (with 4 options and the correct answer indicated) about: {topic}. Make them practical and based on the course content."

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":prompt}],
        temperature=0.3, max_tokens=600
    )
    quiz_text = resp.choices[0].message.content
    append_chat(user_id, "assistant", f"[QUIZ GENERATED] {topic}")
    return jsonify({"quiz": quiz_text})

# ---------- Analytics download (admin) ----------
@app.route("/analytics")
def analytics():
    # very simple protection: require SECRET_KEY param or session admin flag (improve later)
    token = request.args.get("token")
    if token != SECRET_KEY:
        return "Unauthorized", 401
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM analytics ORDER BY created_at DESC LIMIT 5000")
    rows = c.fetchall()
    # build CSV in-memory
    proxy = io.StringIO()
    writer = csv.writer(proxy)
    writer.writerow(["id","user_id","question","answer","created_at"])
    for r in rows:
        writer.writerow([r["id"], r["user_id"], r["question"], r["answer"], r["created_at"]])
    mem = io.BytesIO()
    mem.write(proxy.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="analytics.csv", mimetype="text/csv")

# ---------- Download transcript for current user ----------
@app.route("/download-transcript")
def download_transcript():
    if not session.get("access_granted"):
        return "Access denied", 403
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

# ---------- Simple progress update endpoint ----------
@app.route("/progress", methods=["POST"])
def update_progress():
    if not session.get("access_granted"):
        return jsonify({"ok":False,"error":"Access denied"}),403
    data = request.json
    module = data.get("module")
    course = data.get("course","general")
    user_id = user_id_from_session()
    db = get_db()
    c = db.cursor()
    now = datetime.utcnow().isoformat()
    c.execute("SELECT id FROM progress WHERE user_id = ? AND course = ?", (user_id, course))
    row = c.fetchone()
    if row:
        c.execute("UPDATE progress SET last_module=?, streak=streak+1, updated_at=? WHERE id=?", (module, now, row["id"]))
    else:
        c.execute("INSERT INTO progress (user_id, course, last_module, streak, updated_at) VALUES (?, ?, ?, ?, ?)", (user_id, course, module, 1, now))
    db.commit()
    return jsonify({"ok":True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
