import os

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
TIMEOUT = 120    # one chat turn makes several model calls

st.set_page_config(page_title="GenAI Assistant", page_icon="💬")


def init_state():
    st.session_state.setdefault("token", None)
    st.session_state.setdefault("username", None)
    st.session_state.setdefault("session_id", None)
    st.session_state.setdefault("messages", [])


def logout():
    st.session_state.token = None
    st.session_state.username = None
    st.session_state.session_id = None
    st.session_state.messages = []


def api(method, path, **kwargs):
    headers = {}
    token = st.session_state.token
    if token:
        headers["Authorization"] = f"Token {token}"
    try:
        response = httpx.request(method, f"{API_URL}{path}", headers=headers, timeout=TIMEOUT, **kwargs)
    except httpx.HTTPError:
        return None
    if response.status_code == 401 and token:    # token expired: back to the login screen
        logout()
        st.rerun()
    return response


def flatten_errors(data):
    parts = []
    if isinstance(data, dict):
        for value in data.values():
            parts.extend(value if isinstance(value, list) else [value])
    return " ".join(str(p) for p in parts) or "Request failed."


def login_screen():
    st.title("GenAI Assistant")
    login_tab, register_tab = st.tabs(["Log in", "Register"])
    with login_tab:
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in")
        if submitted:
            response = api("POST", "/login", json={"username": username, "password": password})
            if response is None:
                st.error("Cannot reach the server.")
            elif response.status_code == 200:
                st.session_state.token = response.json()["token"]
                st.session_state.username = username
                st.rerun()
            else:
                st.error("Invalid username or password.")
    with register_tab:
        with st.form("register"):
            new_username = st.text_input("Choose a username")
            new_password = st.text_input("Choose a password", type="password")
            created = st.form_submit_button("Create account")
        if created:
            response = api("POST", "/register", json={"username": new_username, "password": new_password})
            if response is None:
                st.error("Cannot reach the server.")
            elif response.status_code == 201:
                st.success("Account created. Log in on the first tab.")
            else:
                st.error(flatten_errors(response.json()))


def render_assistant_extras(msg):
    if msg.get("route"):
        st.caption(f"Route: {msg['route']}")
    if msg.get("tool_output"):
        with st.expander("Tool used: get_weather"):
            st.text(msg["tool_output"])
    sources = msg.get("sources") or []
    if sources:
        with st.expander(f"Sources ({len(sources)})"):
            for s in sources:
                st.text(f"{s['title']} (document {s['document_id']})")
                st.text(s["chunk_text"])    # st.text, so document content is never rendered as markdown
                st.divider()


def sidebar():
    with st.sidebar:
        st.text(f"Signed in as {st.session_state.username}")
        if st.button("New chat"):
            st.session_state.session_id = None
            st.session_state.messages = []
            st.rerun()
        if st.button("Log out"):
            logout()
            st.rerun()
        st.divider()
        st.subheader("Documents")
        uploaded = st.file_uploader("Upload a PDF or TXT file", type=["pdf", "txt"])
        if uploaded and st.button("Upload and ingest"):
            with st.spinner("Reading and indexing..."):
                response = api("POST", "/api/upload-doc", files={"file": (uploaded.name, uploaded.getvalue())})
            if response is None:
                st.error("Cannot reach the server.")
            elif response.status_code == 201:
                data = response.json()
                pages = f", {data['page_count']} page(s)" if "page_count" in data else ""
                st.success(f"Ingested {data['title']}: {data['chunk_count']} chunk(s){pages}")
            else:
                st.error(response.json().get("error", "Upload failed."))
        listing = api("GET", "/documents", params={"page_size": 100})
        if listing is not None and listing.status_code == 200:
            data = listing.json()
            st.caption(f"{data['count']} document(s)")
            for doc in data["results"][:15]:
                st.text(f"• {doc['title']}")


def chat_screen():
    sidebar()
    st.title("GenAI Assistant")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                render_assistant_extras(msg)

    prompt = st.chat_input("Ask about your documents, or the weather...")
    if not prompt:
        return
    with st.chat_message("user"):
        st.markdown(prompt)
    payload = {"message": prompt}
    if st.session_state.session_id:
        payload["session_id"] = st.session_state.session_id
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = api("POST", "/api/chat", json=payload)
        if response is None:
            st.error("Cannot reach the server.")
        elif response.status_code != 200:
            st.error(flatten_errors(response.json()) if response.status_code == 400
                     else response.json().get("error", "Something went wrong."))
        else:
            data = response.json()
            st.session_state.session_id = data["session_id"]
            assistant_msg = {
                "role": "assistant",
                "content": data["answer"],
                "route": data["route"],
                "tool_output": data["tool_output"],
                "sources": data["sources"],
            }
            st.markdown(assistant_msg["content"])
            render_assistant_extras(assistant_msg)
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state.messages.append(assistant_msg)


init_state()
if st.session_state.token:
    chat_screen()
else:
    login_screen()