"""RAG pipeline: PDF -> chunks -> embeddings (ChromaDB) -> Groq answer.
The embedding model is loaded once per server process."""
import os, threading, warnings
warnings.filterwarnings("ignore")
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import fitz  # PyMuPDF
import chromadb
from groq import Groq
from sentence_transformers import SentenceTransformer

BASE = os.path.dirname(os.path.abspath(__file__))
EMBED_MODEL = "all-MiniLM-L6-v2"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
PREFERRED_MODELS = [
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma2-9b-it",
]
CHUNK_SIZE, OVERLAP = 800, 150
REFUSAL = "I couldn't find the answer to that in your document."

SYSTEM = f"""You are a study assistant. Answer the question using ONLY the excerpts provided.
Rules:
- Do not use outside knowledge and do not guess.
- If the excerpts do not contain the answer, reply with exactly this sentence and nothing else: {REFUSAL}
- Be clear and concise. Use short paragraphs or bullet points when it helps studying."""

_model = None
_lock = threading.Lock()
_collection = None
_groq = None
_active_groq_model = None
_unavailable_models = set()

def model():
    global _model
    with _lock:
        if _model is None:
            _model = SentenceTransformer(EMBED_MODEL)
    return _model

def collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=os.path.join(BASE, "chroma_db"))
        _collection = client.get_or_create_collection("study_chunks", metadata={"hnsw:space": "cosine"})
    return _collection

def groq_client():
    global _groq
    if _groq is None:
        _groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq

def _select_fallback_model():
    global _active_groq_model
    try:
        models_resp = groq_client().models.list()
        available = [
            m.id for m in models_resp.data
            if getattr(m, "active", True)
            and m.id not in _unavailable_models
            and not any(skip in m.id.lower() for skip in ("whisper", "tts", "guard", "safeguard", "orpheus", "embed"))
        ]
    except Exception:
        available = [m for m in PREFERRED_MODELS if m not in _unavailable_models]

    for pref in PREFERRED_MODELS:
        if pref in available:
            _active_groq_model = pref
            return _active_groq_model
    if available:
        _active_groq_model = available[0]
        return _active_groq_model
    return None

def _chat_with_fallback(messages):
    global _active_groq_model
    current = _active_groq_model or os.getenv("GROQ_MODEL", GROQ_MODEL)
    last_err = None
    for _ in range(5):
        if not current:
            break
        try:
            return groq_client().chat.completions.create(
                model=current,
                temperature=0.1,
                messages=messages,
            )
        except Exception as e:
            last_err = e
            err_str = str(e)
            if "model_not_found" in err_str or "404" in err_str or "model_decommissioned" in err_str:
                _unavailable_models.add(current)
                current = _select_fallback_model()
                if current:
                    print(f"[Groq] Model unavailable, automatically switching to: {current}")
                    continue
                raise RuntimeError(
                    "Your Groq API key does not have access to any chat models. "
                    "Open https://console.groq.com/settings/limits (or Project -> Limits / Model Permissions) "
                    "and enable models like 'llama-3.3-70b-versatile' or 'llama-3.1-8b-instant' for your project."
                ) from e
            raise
    raise last_err

def chunk_text(text):
    text = " ".join(text.split())
    out, start = [], 0
    while start < len(text):
        piece = text[start:start + CHUNK_SIZE].strip()
        if piece:
            out.append(piece)
        start += CHUNK_SIZE - OVERLAP
    return out

def ingest(pdf_path, doc_id):
    """Returns (pages, chunk_count). Raises ValueError if no text."""
    chunks, metas, ids = [], [], []
    with fitz.open(pdf_path) as pdf:
        pages = len(pdf)
        for i, page in enumerate(pdf, start=1):
            for j, c in enumerate(chunk_text(page.get_text())):
                chunks.append(c)
                metas.append({"document_id": doc_id, "page": i})
                ids.append(f"{doc_id}-{i}-{j}")
    if not chunks:
        raise ValueError("No readable text found. Scanned PDFs are not supported.")
    embeddings = model().encode(chunks, show_progress_bar=False).tolist()
    collection().add(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metas)
    return pages, len(chunks)

def answer(doc_id, question):
    q_emb = model().encode([question], show_progress_bar=False).tolist()
    res = collection().query(query_embeddings=q_emb, n_results=5, where={"document_id": doc_id})
    docs = res["documents"][0] if res["documents"] else []
    metas = res["metadatas"][0] if res["metadatas"] else []
    if not docs:
        return REFUSAL, [], False
    context = "\n\n".join(f"[Page {m['page']}]\n{d}" for d, m in zip(docs, metas))
    resp = _chat_with_fallback([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Excerpts:\n{context}\n\nQuestion: {question}"},
    ])
    text = resp.choices[0].message.content.strip()
    found = REFUSAL not in text
    pages = sorted({m["page"] for m in metas}) if found else []
    return text, pages, found
