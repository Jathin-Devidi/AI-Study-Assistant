import os, uuid, threading
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from bson import ObjectId
from bson.errors import InvalidId
from flask import Flask, render_template, request, jsonify, abort
from pymongo import MongoClient
from werkzeug.exceptions import RequestEntityTooLarge
import rag

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=5000)
db = mongo[os.getenv("MONGO_DB", "ai_study_assistant")]
documents = db["documents"]
history = db["chat_history"]
history.create_index([("document_id", 1), ("created_at", 1)])

def oid(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None

def get_doc(doc_id):
    _id = oid(doc_id)
    return documents.find_one({"_id": _id}) if _id else None

def process(doc_id, path):
    try:
        pages, _ = rag.ingest(path, doc_id)
        documents.update_one({"_id": ObjectId(doc_id)}, {"$set": {"status": "ready", "pages": pages}})
    except Exception as e:
        documents.update_one({"_id": ObjectId(doc_id)}, {"$set": {"status": "failed", "error": str(e)[:400]}})

@app.route("/")
def home():
    docs = list(documents.find().sort("created_at", -1).limit(12))
    return render_template("home.html", docs=docs)

@app.route("/ask/<doc_id>")
def ask_page(doc_id):
    doc = get_doc(doc_id)
    if not doc:
        abort(404)
    msgs = list(history.find({"document_id": doc_id}).sort("created_at", 1))
    return render_template("ask.html", doc=doc, history=msgs)

@app.post("/upload")
def upload():
    f = request.files.get("pdf")
    if not f or not f.filename:
        return jsonify(error="Choose a PDF to upload."), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify(error="Only PDF files are allowed."), 400
    if f.stream.read(5) != b"%PDF-":
        return jsonify(error="That file is not a valid PDF."), 400
    f.stream.seek(0)
    stored = f"{uuid.uuid4()}.pdf"
    path = os.path.join(UPLOAD_DIR, stored)
    f.save(path)
    res = documents.insert_one({
        "original_name": f.filename[:250], "stored_name": stored, "status": "processing",
        "error": None, "pages": None, "created_at": datetime.now(timezone.utc),
    })
    doc_id = str(res.inserted_id)
    threading.Thread(target=process, args=(doc_id, path), daemon=True).start()
    return jsonify(id=doc_id)

@app.get("/api/documents/<doc_id>/status")
def status(doc_id):
    doc = get_doc(doc_id)
    if not doc:
        return jsonify(error="Not found"), 404
    return jsonify(status=doc["status"], error=doc.get("error"))

@app.post("/api/ask")
def ask():
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()[:1000]
    if not question:
        return jsonify(error="Type a question first."), 400
    doc = get_doc(data.get("documentId"))
    if not doc:
        return jsonify(error="Document not found."), 404
    if doc["status"] != "ready":
        return jsonify(error="This document is not ready yet."), 409
    doc_id = str(doc["_id"])
    try:
        text, pages, found = rag.answer(doc_id, question)
    except Exception as e:
        return jsonify(error=f"Could not get an answer: {e}"), 500
    history.insert_one({"document_id": doc_id, "question": question, "answer": text,
                        "sources": pages, "created_at": datetime.now(timezone.utc)})
    return jsonify(answer=text, sources=pages, found=found)

@app.errorhandler(RequestEntityTooLarge)
def too_large(e):
    return jsonify(error="File is larger than 10 MB."), 413

if __name__ == "__main__":
    mongo.admin.command("ping")  # fail fast with a clear error if MongoDB isn't reachable
    app.run(port=int(os.getenv("PORT", 3000)), debug=False, threaded=True)
