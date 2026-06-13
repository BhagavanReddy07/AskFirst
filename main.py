"""
main.py — FastAPI backend
Endpoints:
  GET    /threads                  → list all threads
  POST   /threads                  → create a new thread
  DELETE /threads/{id}             → delete a thread
  PATCH  /threads/{id}/rename      → rename a thread
  GET    /threads/{id}/messages    → fetch messages for a thread
  POST   /threads/{id}/chat        → send a message + get AI reply
"""

import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

import database as db

load_dotenv()

# ── LLM config (read from .env) ───────────────────────────────────────────────

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()  # openai | claude | groq | gemini
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "")  # blank = use provider default


# ── LLM caller ────────────────────────────────────────────────────────────────

def get_llm_reply(messages: list[dict]) -> str:
    """
    Call the configured LLM and return the reply string.
    `messages` follows the OpenAI format:
      [{"role": "system"|"user"|"assistant", "content": "..."}]
    """

    # ── OpenAI ────────────────────────────────────────────────────────────────
    if LLM_PROVIDER == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=LLM_API_KEY)
        resp = client.chat.completions.create(
            model=LLM_MODEL or "gpt-4o-mini",
            messages=messages,
            max_tokens=1024,
        )
        return resp.choices[0].message.content

    # ── Anthropic Claude ──────────────────────────────────────────────────────
    elif LLM_PROVIDER == "claude":
        import anthropic
        client = anthropic.Anthropic(api_key=LLM_API_KEY)

        # Claude keeps system text separate from the messages array
        system_text = ""
        chat_msgs: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            else:
                chat_msgs.append({"role": m["role"], "content": m["content"]})

        resp = client.messages.create(
            model=LLM_MODEL or "claude-3-5-haiku-20241022",
            max_tokens=1024,
            system=system_text.strip() or anthropic.NOT_GIVEN,
            messages=chat_msgs,
        )
        return resp.content[0].text

    # ── Groq (free Llama / Mixtral) ───────────────────────────────────────────
    elif LLM_PROVIDER == "groq":
        from groq import Groq
        client = Groq(api_key=LLM_API_KEY)
        resp = client.chat.completions.create(
            model=LLM_MODEL or "llama3-8b-8192",
            messages=messages,
            max_tokens=1024,
        )
        return resp.choices[0].message.content

    # ── Google Gemini ─────────────────────────────────────────────────────────
    elif LLM_PROVIDER == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=LLM_API_KEY)

        # Extract system prompt — pass as system_instruction for best results
        system_text = ""
        chat_history = []
        last_user_msg = ""

        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            elif m["role"] == "user":
                last_user_msg = m["content"]
                # All but the last user message go into history
                chat_history.append({
                    "role": "user",
                    "parts": [m["content"]]
                })
            elif m["role"] == "assistant":
                chat_history.append({
                    "role": "model",
                    "parts": [m["content"]]
                })

        # Remove the last user message from history (it's sent as the live message)
        if chat_history and chat_history[-1]["role"] == "user":
            chat_history.pop()

        model = genai.GenerativeModel(
            model_name=LLM_MODEL or "gemini-1.5-flash",
            system_instruction=system_text.strip() or None,
        )
        chat = model.start_chat(history=chat_history)
        resp = chat.send_message(last_user_msg)
        return resp.text

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {LLM_PROVIDER!r}. "
            "Choose one of: openai | claude | groq | gemini"
        )


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="AskFirst Mini Chat", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    db.create_tables()   # creates chat.db + tables if they don't exist


# ── Pydantic request schemas ──────────────────────────────────────────────────

class ThreadCreate(BaseModel):
    title: str = "New Thread"

class RenameRequest(BaseModel):
    title: str

class ChatRequest(BaseModel):
    message: str
    context_window: int = 20      # how many past messages from this thread
    universal_memory: bool = True  # inject cross-thread context


# ── Thread endpoints ──────────────────────────────────────────────────────────

@app.get("/threads")
def list_threads():
    return db.get_all_threads()


@app.post("/threads", status_code=201)
def create_thread(body: ThreadCreate):
    return db.create_thread(title=body.title)


@app.delete("/threads/{thread_id}")
def delete_thread(thread_id: int):
    if not db.delete_thread(thread_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"detail": "Thread deleted"}


@app.patch("/threads/{thread_id}/rename")
def rename_thread(thread_id: int, body: RenameRequest):
    thread = db.rename_thread(thread_id, body.title)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


# ── Message endpoints ─────────────────────────────────────────────────────────

@app.get("/threads/{thread_id}/messages")
def get_messages(thread_id: int):
    if not db.get_thread(thread_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    return db.get_thread_messages(thread_id)


# ── Chat endpoint ─────────────────────────────────────────────────────────────

@app.post("/threads/{thread_id}/chat")
def chat(thread_id: int, body: ChatRequest):
    thread = db.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # 1. Persist the user's message
    db.add_message(thread_id, role="user", content=body.message)

    # 2. Build the LLM message list
    llm_messages: list[dict] = []

    # 2a. Base system prompt
    system_prompt = (
        "You are a helpful, friendly AI assistant. "
        "Be concise and accurate. "
        "If you have memory of past conversations, use that context naturally."
    )

    # 2b. Inject universal cross-thread memory (optional)
    if body.universal_memory:
        ctx = db.get_universal_context(exclude_thread_id=thread_id)
        if ctx:
            system_prompt += "\n\n" + ctx

    llm_messages.append({"role": "system", "content": system_prompt})

    # 2c. Recent messages from this thread (context window)
    history = db.get_thread_messages(thread_id, limit=body.context_window)
    for msg in history:
        if msg["role"] in ("user", "assistant"):
            llm_messages.append({"role": msg["role"], "content": msg["content"]})

    # 3. Call LLM
    try:
        reply = get_llm_reply(llm_messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    # 4. Persist the assistant reply
    db.add_message(thread_id, role="assistant", content=reply)

    # 5. Auto-rename thread from first message if still "New Thread"
    if thread["title"] in ("New Thread", "") and body.message:
        db.rename_thread(thread_id, body.message[:60].strip())

    return {"reply": reply}
