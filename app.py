"""
app.py — Streamlit frontend
Run with: streamlit run app.py
Requires the FastAPI backend to be running: uvicorn main:app --reload
"""

import streamlit as st
import requests
import os

# ── Config ───────────────────────────────────────────────────────────────────
# Reads BACKEND_URL from Streamlit secrets (production) or env, fallback to localhost

try:
    BACKEND_URL = st.secrets["BACKEND_URL"]
except Exception:
    BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(
    page_title="AskFirst · Mini Chat",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ───────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── Global ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ── Dark background ── */
.stApp {
    background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
    min-height: 100vh;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: rgba(255,255,255,0.04);
    border-right: 1px solid rgba(255,255,255,0.08);
}

/* ── Chat bubbles ── */
.user-bubble {
    background: linear-gradient(135deg, #6c63ff, #a78bfa);
    color: white;
    padding: 12px 18px;
    border-radius: 18px 18px 4px 18px;
    margin: 8px 0;
    margin-left: 20%;
    box-shadow: 0 4px 15px rgba(108,99,255,0.3);
    font-size: 15px;
    line-height: 1.5;
}

.assistant-bubble {
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.12);
    color: #e2e8f0;
    padding: 12px 18px;
    border-radius: 18px 18px 18px 4px;
    margin: 8px 0;
    margin-right: 20%;
    backdrop-filter: blur(10px);
    font-size: 15px;
    line-height: 1.5;
}

.role-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    opacity: 0.5;
    margin-bottom: 4px;
}

/* ── Thread button styling ── */
.stButton > button {
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.1);
    background: rgba(255,255,255,0.05);
    color: #e2e8f0;
    transition: all 0.2s ease;
}
.stButton > button:hover {
    background: rgba(108,99,255,0.25);
    border-color: #6c63ff;
    transform: translateY(-1px);
}

/* ── Input ── */
.stTextInput > div > div > input, .stChatInput > div > div > input {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 12px !important;
    color: white !important;
}

/* ── Headers ── */
h1, h2, h3 { color: #e2e8f0 !important; }

/* ── Memory badge ── */
.memory-badge {
    display: inline-block;
    background: linear-gradient(90deg, #f59e0b, #ef4444);
    color: white;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 999px;
    letter-spacing: 0.05em;
}

/* ── Scrollable message area ── */
.chat-area {
    max-height: 65vh;
    overflow-y: auto;
    padding: 10px 0;
}

/* ── Thread list active ── */
.active-thread {
    border-left: 3px solid #6c63ff !important;
    background: rgba(108,99,255,0.15) !important;
}

/* ── Hide Streamlit chrome (deploy button, toolbar, footer) ── */
[data-testid="stToolbar"]       { display: none !important; }
[data-testid="stDecoration"]    { display: none !important; }
[data-testid="stStatusWidget"]  { display: none !important; }
.stDeployButton                 { display: none !important; }
footer                          { display: none !important; }
#MainMenu                       { display: none !important; }
</style>
""", unsafe_allow_html=True)


# ── API Helpers ───────────────────────────────────────────────────────────────

def api(method: str, path: str, **kwargs):
    try:
        r = getattr(requests, method)(f"{BACKEND_URL}{path}", timeout=30, **kwargs)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot reach backend. Make sure `uvicorn main:app --reload` is running.")
        st.stop()
    except Exception as e:
        st.error(f"API error: {e}")
        return None


# ── Session state ─────────────────────────────────────────────────────────────

if "active_thread_id" not in st.session_state:
    st.session_state.active_thread_id = None

if "messages_cache" not in st.session_state:
    st.session_state.messages_cache = {}


# ── Sidebar — Thread Management ───────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style='text-align:center; padding: 10px 0 20px'>
        <span style='font-size:28px'>💬</span>
        <h2 style='margin:0; color:#e2e8f0; font-weight:700'>AskFirst</h2>
        <p style='color:#94a3b8; font-size:13px; margin:4px 0 0'>Mini AI Chat</p>
    </div>
    """, unsafe_allow_html=True)

    # New thread button
    if st.button("＋  New Thread", use_container_width=True, key="new_thread_btn"):
        result = api("post", "/threads", json={"title": "New Thread"})
        if result:
            st.session_state.active_thread_id = result["id"]
            st.session_state.messages_cache[result["id"]] = []
            st.rerun()

    st.divider()
    st.markdown("<p style='color:#94a3b8;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase'>Threads</p>", unsafe_allow_html=True)

    threads = api("get", "/threads") or []

    if not threads:
        st.markdown("<p style='color:#64748b;font-size:13px'>No threads yet. Create one above!</p>", unsafe_allow_html=True)

    for thread in threads:
        tid  = thread["id"]
        active = (tid == st.session_state.active_thread_id)
        label  = f"{'▶ ' if active else ''}{thread['title'][:35]}"

        col1, col2 = st.columns([5, 1])
        with col1:
            if st.button(label, key=f"thread_{tid}", use_container_width=True):
                st.session_state.active_thread_id = tid
                st.session_state.messages_cache.pop(tid, None)  # refresh
                st.rerun()
        with col2:
            if st.button("🗑", key=f"del_{tid}", help="Delete thread"):
                api("delete", f"/threads/{tid}")
                if st.session_state.active_thread_id == tid:
                    st.session_state.active_thread_id = None
                st.session_state.messages_cache.pop(tid, None)
                st.rerun()

    st.divider()
    st.markdown("""
    <div style='padding: 10px 0'>
        <span class='memory-badge'>🧠 Universal Memory ON</span>
        <p style='color:#64748b;font-size:12px;margin-top:8px;line-height:1.6'>
        Every thread shares a cross-thread context window so the AI remembers
        your past conversations across all threads.
        </p>
    </div>
    """, unsafe_allow_html=True)


# ── Main Chat Area ────────────────────────────────────────────────────────────

if st.session_state.active_thread_id is None:
    # Welcome screen
    st.markdown("""
    <div style='display:flex;flex-direction:column;align-items:center;justify-content:center;
                height:70vh;text-align:center'>
        <div style='font-size:64px'>💬</div>
        <h1 style='color:#e2e8f0;font-weight:700;margin:16px 0 8px'>Welcome to AskFirst</h1>
        <p style='color:#94a3b8;font-size:17px;max-width:480px;line-height:1.7'>
            Create a new thread in the sidebar to start chatting.<br>
            Every conversation is saved — your AI remembers everything across threads.
        </p>
        <div style='margin-top:24px;display:flex;gap:16px'>
            <div style='background:rgba(108,99,255,0.15);border:1px solid rgba(108,99,255,0.3);
                        border-radius:12px;padding:14px 20px;color:#a78bfa;font-size:14px'>
                🗂 Multiple Threads
            </div>
            <div style='background:rgba(245,158,11,0.15);border:1px solid rgba(245,158,11,0.3);
                        border-radius:12px;padding:14px 20px;color:#fbbf24;font-size:14px'>
                🧠 Universal Memory
            </div>
            <div style='background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);
                        border-radius:12px;padding:14px 20px;color:#34d399;font-size:14px'>
                💾 SQLite Persistence
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

else:
    tid = st.session_state.active_thread_id

    # Find thread title
    thread_title = next(
        (t["title"] for t in (api("get", "/threads") or []) if t["id"] == tid),
        "Thread"
    )

    # Header — title auto-set from first message (ChatGPT-style), no rename widget needed
    st.markdown(f"""
    <div style='display:flex;align-items:center;gap:10px;padding:4px 0 2px'>
        <span style='font-size:20px'>💬</span>
        <h2 style='color:#e2e8f0;margin:0;font-size:20px;font-weight:600;
                   white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:700px'>
            {thread_title}
        </h2>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Load messages
    if tid not in st.session_state.messages_cache:
        msgs = api("get", f"/threads/{tid}/messages") or []
        st.session_state.messages_cache[tid] = msgs

    messages = st.session_state.messages_cache[tid]

    # Render messages
    if not messages:
        st.markdown("""
        <div style='text-align:center;padding:60px 0;color:#64748b'>
            <div style='font-size:40px'>🌱</div>
            <p style='font-size:15px;margin-top:12px'>No messages yet. Say something!</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        for msg in messages:
            if msg["role"] == "user":
                st.markdown(f"""
                <div class='role-label' style='text-align:right;color:#a78bfa'>You</div>
                <div class='user-bubble'>{msg['content']}</div>
                """, unsafe_allow_html=True)
            elif msg["role"] == "assistant":
                st.markdown(f"""
                <div class='role-label' style='color:#94a3b8'>AI</div>
                <div class='assistant-bubble'>{msg['content']}</div>
                """, unsafe_allow_html=True)

    st.divider()

    # Chat input
    user_input = st.chat_input("Type a message…", key=f"input_{tid}")

    if user_input and user_input.strip():
        with st.spinner("AI is thinking…"):
            result = api(
                "post",
                f"/threads/{tid}/chat",
                json={
                    "message": user_input.strip(),
                    "context_window": 20,
                    "universal_memory": True,
                }
            )

        if result:
            # Refresh messages from backend
            st.session_state.messages_cache.pop(tid, None)
            st.rerun()
