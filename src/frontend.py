import os
import requests
import streamlit as st

API_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="ArduChat", page_icon="🚁", layout="wide")

# ---------------- Sidebar: session list + new chat ----------------
with st.sidebar:
    st.title("🚁 ArduChat")

    if st.button("➕ New chat", use_container_width=True):
        resp = requests.post(f"{API_URL}/sessions", json={"title": "New chat"})
        resp.raise_for_status()
        st.session_state.session_id = resp.json()["session_id"]
        st.session_state.messages = []
        st.rerun()

    st.markdown("---")
    st.subheader("History")

    try:
        sessions = requests.get(f"{API_URL}/sessions").json()
    except Exception as e:
        sessions = []
        st.error(f"Backend not reachable: {e}")

    for s in sessions:
        cols = st.columns([5, 1])
        label = s["title"] or "Untitled"
        if cols[0].button(label, key=f"sel_{s['id']}", use_container_width=True):
            st.session_state.session_id = s["id"]
            msgs = requests.get(f"{API_URL}/sessions/{s['id']}/messages").json()
            st.session_state.messages = [
                {"role": "user" if m["role"] == "human" else "assistant", "content": m["content"]}
                for m in msgs
            ]
            st.rerun()
        if cols[1].button("🗑", key=f"del_{s['id']}"):
            requests.delete(f"{API_URL}/sessions/{s['id']}")
            if st.session_state.get("session_id") == s["id"]:
                st.session_state.session_id = None
                st.session_state.messages = []
            st.rerun()

# ---------------- Init state ----------------
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []

st.title("ArduPilot Copter Docs Assistant")

if st.session_state.session_id is None:
    st.info("Start a new chat from the sidebar to begin.")
    st.stop()

# ---------------- Render existing messages ----------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------- Chat input ----------------
user_input = st.chat_input("Ask about ArduPilot Copter...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                resp = requests.post(
                    f"{API_URL}/chat",
                    json={"session_id": st.session_state.session_id, "message": user_input},
                    timeout=180,
                )
                resp.raise_for_status()
                answer = resp.json()["answer"]
            except Exception as e:
                answer = f"Error: {e}"
            st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})