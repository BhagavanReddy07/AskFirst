"""
app.py - Self-contained Streamlit chat app (no FastAPI needed)
Deploy free: https://share.streamlit.io
"""
import os
import streamlit as st
from dotenv import load_dotenv
load_dotenv()

import database as db

# Config - reads from Streamlit secrets on cloud, .env locally
def _secret(key, default=""):
    try: return st.secrets[key]
    except: return os.getenv(key, default)

LLM_PROVIDER = _secret("LLM_PROVIDER", "groq")
LLM_API_KEY  = _secret("LLM_API_KEY", "")
LLM_MODEL    = _secret("LLM_MODEL", "llama-3.3-70b-versatile")
db.DB_PATH   = _secret("DB_PATH", db.DB_PATH)
db.create_tables()

st.set_page_config(page_title="AskFirst", page_icon="💬", layout="wide")

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
.stApp{background:linear-gradient(135deg,#0f0f1a,#1a1a2e,#16213e);}
section[data-testid="stSidebar"]{background:rgba(255,255,255,0.04);border-right:1px solid rgba(255,255,255,0.08);}
.user-bubble{background:linear-gradient(135deg,#6c63ff,#a78bfa);color:white;padding:12px 18px;
  border-radius:18px 18px 4px 18px;margin:8px 0;margin-left:20%;
  box-shadow:0 4px 15px rgba(108,99,255,0.3);font-size:15px;line-height:1.5;}
.ai-bubble{background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.12);
  color:#e2e8f0;padding:12px 18px;border-radius:18px 18px 18px 4px;
  margin:8px 0;margin-right:20%;font-size:15px;line-height:1.5;}
.lbl{font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;opacity:.5;margin-bottom:4px;}
.stButton>button{border-radius:10px;border:1px solid rgba(255,255,255,0.1);
  background:rgba(255,255,255,0.05);color:#e2e8f0;transition:all .2s ease;}
.stButton>button:hover{background:rgba(108,99,255,0.25);border-color:#6c63ff;}
h1,h2,h3{color:#e2e8f0 !important;}
.mbadge{display:inline-block;background:linear-gradient(90deg,#f59e0b,#ef4444);
  color:white;font-size:11px;font-weight:600;padding:3px 10px;border-radius:999px;}
[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"],
.stDeployButton,footer,#MainMenu{display:none !important;}
</style>""", unsafe_allow_html=True)


def llm_reply(messages):
    if LLM_PROVIDER == "groq":
        from groq import Groq
        r = Groq(api_key=LLM_API_KEY).chat.completions.create(
            model=LLM_MODEL or "llama-3.3-70b-versatile", messages=messages, max_tokens=1024)
        return r.choices[0].message.content
    elif LLM_PROVIDER == "openai":
        from openai import OpenAI
        r = OpenAI(api_key=LLM_API_KEY).chat.completions.create(
            model=LLM_MODEL or "gpt-4o-mini", messages=messages, max_tokens=1024)
        return r.choices[0].message.content
    elif LLM_PROVIDER == "claude":
        import anthropic
        c = anthropic.Anthropic(api_key=LLM_API_KEY)
        sys = "\n".join(m["content"] for m in messages if m["role"]=="system")
        msgs = [m for m in messages if m["role"]!="system"]
        r = c.messages.create(model=LLM_MODEL or "claude-3-5-haiku-20241022",
            max_tokens=1024, system=sys or anthropic.NOT_GIVEN, messages=msgs)
        return r.content[0].text
    elif LLM_PROVIDER == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=LLM_API_KEY)
        sys, hist, last = "", [], ""
        for m in messages:
            if m["role"]=="system": sys+=m["content"]+"\n"
            elif m["role"]=="user": last=m["content"]; hist.append({"role":"user","parts":[m["content"]]})
            else: hist.append({"role":"model","parts":[m["content"]]})
        if hist and hist[-1]["role"]=="user": hist.pop()
        mdl = genai.GenerativeModel(LLM_MODEL or "gemini-2.0-flash", system_instruction=sys.strip() or None)
        return mdl.start_chat(history=hist).send_message(last).text
    raise ValueError(f"Unknown provider: {LLM_PROVIDER}")


def chat(thread_id, user_msg):
    db.add_message(thread_id, "user", user_msg)
    sys = ("You are a helpful AI assistant. Be concise and friendly. "
           "Use memory of past conversations naturally.")
    ctx = db.get_universal_context(exclude_thread_id=thread_id)
    if ctx: sys += "\n\n" + ctx
    history = [{"role":"system","content":sys}]
    for m in db.get_thread_messages(thread_id, limit=20):
        if m["role"] in ("user","assistant"):
            history.append({"role":m["role"],"content":m["content"]})
    reply = llm_reply(history)
    db.add_message(thread_id, "assistant", reply)
    t = db.get_thread(thread_id)
    if t and t["title"] in ("New Thread",""):
        db.rename_thread(thread_id, user_msg[:60].strip())
    return reply


# Session state
if "active" not in st.session_state: st.session_state.active = None
if "cache"  not in st.session_state: st.session_state.cache  = {}

# Sidebar
with st.sidebar:
    st.markdown("""<div style='text-align:center;padding:10px 0 20px'>
        <span style='font-size:28px'>💬</span>
        <h2 style='margin:0;color:#e2e8f0;font-weight:700'>AskFirst</h2>
        <p style='color:#94a3b8;font-size:13px;margin:4px 0 0'>Mini AI Chat</p>
    </div>""", unsafe_allow_html=True)

    if st.button("＋  New Thread", use_container_width=True):
        t = db.create_thread("New Thread")
        st.session_state.active = t["id"]
        st.session_state.cache[t["id"]] = []
        st.rerun()

    st.divider()
    st.markdown("<p style='color:#94a3b8;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase'>Threads</p>", unsafe_allow_html=True)

    threads = db.get_all_threads()
    if not threads:
        st.markdown("<p style='color:#64748b;font-size:13px'>No threads yet.</p>", unsafe_allow_html=True)

    for t in threads:
        tid = t["id"]; active = tid == st.session_state.active
        c1, c2 = st.columns([5,1])
        with c1:
            if st.button(f"{'▶ ' if active else ''}{t['title'][:34]}", key=f"t{tid}", use_container_width=True):
                st.session_state.active = tid
                st.session_state.cache.pop(tid, None)
                st.rerun()
        with c2:
            if st.button("🗑", key=f"d{tid}"):
                db.delete_thread(tid)
                if st.session_state.active == tid: st.session_state.active = None
                st.session_state.cache.pop(tid, None)
                st.rerun()

    st.divider()
    st.markdown("<div style='padding:10px 0'><span class='mbadge'>🧠 Universal Memory ON</span><p style='color:#64748b;font-size:12px;margin-top:8px;line-height:1.6'>New threads remember all past conversations.</p></div>", unsafe_allow_html=True)

# Main area
if st.session_state.active is None:
    st.markdown("""<div style='display:flex;flex-direction:column;align-items:center;justify-content:center;height:70vh;text-align:center'>
        <div style='font-size:64px'>💬</div>
        <h1 style='color:#e2e8f0;font-weight:700;margin:16px 0 8px'>Welcome to AskFirst</h1>
        <p style='color:#94a3b8;font-size:17px;max-width:480px;line-height:1.7'>
            Create a new thread to start chatting.<br>Your AI remembers everything across threads.
        </p>
    </div>""", unsafe_allow_html=True)
else:
    tid = st.session_state.active
    thread = db.get_thread(tid)
    if not thread: st.session_state.active = None; st.rerun()

    st.markdown(f"""<div style='display:flex;align-items:center;gap:10px;padding:4px 0 2px'>
        <span style='font-size:20px'>💬</span>
        <h2 style='color:#e2e8f0;margin:0;font-size:20px;font-weight:600;
                   white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:700px'>
            {thread['title']}</h2></div>""", unsafe_allow_html=True)
    st.divider()

    if tid not in st.session_state.cache:
        st.session_state.cache[tid] = db.get_thread_messages(tid)

    for msg in st.session_state.cache[tid]:
        if msg["role"] == "user":
            st.markdown(f"<div class='lbl' style='text-align:right;color:#a78bfa'>You</div><div class='user-bubble'>{msg['content']}</div>", unsafe_allow_html=True)
        elif msg["role"] == "assistant":
            st.markdown(f"<div class='lbl' style='color:#94a3b8'>AI</div><div class='ai-bubble'>{msg['content']}</div>", unsafe_allow_html=True)

    if not st.session_state.cache[tid]:
        st.markdown("<div style='text-align:center;padding:60px 0;color:#64748b'><div style='font-size:40px'>🌱</div><p style='font-size:15px;margin-top:12px'>No messages yet. Say something!</p></div>", unsafe_allow_html=True)

    st.divider()
    user_input = st.chat_input("Type a message…")
    if user_input and user_input.strip():
        with st.spinner("Thinking…"):
            try: chat(tid, user_input.strip())
            except Exception as e: st.error(f"Error: {e}"); st.stop()
        st.session_state.cache.pop(tid, None)
        st.rerun()
