import os
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import streamlit as st
from google import genai
from google.genai import types
from gemini_export import get_calendar_export

# Load environment variables from .env file if present
load_dotenv()

st.set_page_config(
    page_title="My MU Calendar Assistant",
    page_icon="💻",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ---------------------------------------------------------
# Configuration & Context (No Sidebar)
# ---------------------------------------------------------
# 1. API Key Handling: Always retrieve from Streamlit secrets (.streamlit/secrets.toml)
api_key = ""
try:
    if "gemini_api_key" in st.secrets:
        api_key = st.secrets["gemini_api_key"]
    elif "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

if not api_key:
    api_key = os.getenv("GEMINI_API_KEY", "")

# 2. Model & Generation Settings (Gemini 3.5 Flash Lite with Gemini 3.1 Flash Lite alternative)
PRIMARY_MODEL = "gemini-3.5-flash-lite"
ALTERNATIVE_MODEL = "gemini-3.1-flash-lite"
selected_model = PRIMARY_MODEL
temperature = 0.7

current_dir = os.path.dirname(os.path.abspath(__file__))

# Course JSON files to load alongside the calendar export
COURSE_JSON_FILES = ["ITCS544.json", "ITCS503.json", "ITCS509.json", "ITCS525.json"]

# 3. Calendar Data Sync & Loading
@st.cache_data(ttl=300, show_spinner="Syncing latest course calendar...")
def load_calendar_data():
    # Step 1: Load each course schedule JSON file
    course_schedules = {}
    for course_file in COURSE_JSON_FILES:
        course_path = os.path.join(current_dir, course_file)
        if os.path.exists(course_path):
            try:
                with open(course_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    course_code = data.get("metadata", {}).get("course_code", course_file.replace(".json", ""))
                    course_schedules[course_code] = data
            except Exception as e:
                print(f"Warning: failed to load {course_file}: {e}")

    # Step 2: Directly call gemini_export to get calendar dictionary in memory (no JSON dump needed)
    calendar_export = None
    try:
        calendar_export = get_calendar_export()
    except Exception as e:
        print(f"Warning: failed to fetch calendar data: {e}")

    return {
        "calendar_export": calendar_export,
        "course_schedules": course_schedules
    }

loaded = load_calendar_data()
calendar_data = loaded.get("calendar_export")
course_schedules = loaded.get("course_schedules", {})
calendar_loaded = calendar_data is not None or len(course_schedules) > 0


# ---------------------------------------------------------
# Build System Instruction
# ---------------------------------------------------------
tz_ict = timezone(timedelta(hours=7))
current_time_str = datetime.now(tz_ict).strftime("%A, %B %d, %Y at %H:%M ICT (UTC+7)")

system_instruction = f"""You are a helpful, knowledgeable, and friendly AI assistant powered by Google Gemini.
Current reference date and time: {current_time_str}.
"""

if calendar_loaded:
    system_instruction += "\nThe user is a student at Mahidol University Faculty of ICT.\n"

    # Inject per-course schedule data (ITCS544, ITCS503, ITCS509, ITCS525)
    if course_schedules:
        system_instruction += "\n## Course Schedules & Topics\n"
        for code, data in course_schedules.items():
            meta = data.get("metadata", {})
            schedules = data.get("schedules", [])
            system_instruction += f"""
### {code} – {meta.get("course_name", "")}
{json.dumps(schedules, indent=2)}
"""

    # Inject calendar deadlines, cancellations & make-up events
    if calendar_data:
        system_instruction += f"""
## Moodle Calendar: Deadlines, Cancellations & Make-up Classes
{json.dumps(calendar_data, indent=2)}
"""

    system_instruction += """
When answering questions about classes, homework, or schedule:
- Use exact course codes (e.g. ITCS 509, ITCS 525, ITCS 503, ITCS 544, ITCS 514).
- Use the course schedule topic data to provide detailed, week-by-week lecture information.
- Distinguish active make-up classes from cancelled sessions.
- Provide clear, actionable deadlines with exact due dates.
"""


# ---------------------------------------------------------
# Session State Initialization & Chat Session
# ---------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

def get_chat_history_contents():
    history = []
    for m in st.session_state.messages:
        if m.get("content"):
            role = "model" if m["role"] == "assistant" else "user"
            history.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=m["content"])]
                )
            )
    return history

def init_chat_session(model_name=None):
    if not api_key:
        return None
    st.session_state.client = genai.Client(api_key=api_key)
    st.session_state.current_api_key = api_key
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature
    )
    existing_history = get_chat_history_contents() if st.session_state.messages else None
    if existing_history and existing_history[-1].role == "user":
        existing_history.pop()
        
    target_model = model_name or selected_model
    try:
        st.session_state.chat = st.session_state.client.chats.create(
            model=target_model,
            config=config,
            history=existing_history if existing_history else None
        )
        st.session_state.active_model = target_model
    except Exception as e:
        # Fallback to alternative model if primary fails
        fallback_model = ALTERNATIVE_MODEL if target_model == PRIMARY_MODEL else PRIMARY_MODEL
        st.session_state.chat = st.session_state.client.chats.create(
            model=fallback_model,
            config=config,
            history=existing_history if existing_history else None
        )
        st.session_state.active_model = fallback_model
    return st.session_state.chat

# Maintain client & chat session in session_state
if api_key:
    if "client" not in st.session_state or st.session_state.get("current_api_key") != api_key:
        try:
            st.session_state.client = genai.Client(api_key=api_key)
            st.session_state.current_api_key = api_key
        except Exception as e:
            st.error(f"Failed to initialize Gemini Client: {e}")

    if "chat" not in st.session_state and "client" in st.session_state:
        try:
            init_chat_session()
        except Exception as e:
            st.error(f"Failed to initialize Chat session: {e}")

# ---------------------------------------------------------
# Main UI
# ---------------------------------------------------------
header_col1, header_col2 = st.columns([6, 1], vertical_alignment="bottom")
with header_col1:
    st.title("💻 My MU Calendar Assistant")
    n_courses = len(course_schedules)
    if n_courses > 0 and calendar_data:
        status_badge = f"📅 {n_courses} courses + calendar loaded"
    elif n_courses > 0:
        status_badge = f"📚 {n_courses} course schedules loaded"
    elif calendar_data:
        status_badge = "📅 Calendar loaded"
    else:
        status_badge = "🤖 General Assistant"
    active_m = st.session_state.get("active_model", selected_model)
    st.caption(f"Model: `{active_m}` (Alt: `{ALTERNATIVE_MODEL}`) | {status_badge}")
with header_col2:
    if st.button("🗑️ Clear", help="Clear conversation history", use_container_width=True):
        st.session_state.messages = []
        if "chat" in st.session_state:
            del st.session_state["chat"]
        st.rerun()

st.divider()

# Notice if API Key is missing
if not api_key:
    st.error("⚠️ No Gemini API key found in `.streamlit/secrets.toml`. Please add `gemini_api_key = \"...\"` to your secrets file.")
    st.stop()

# Display Chat History
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Quick Suggestions if chat is empty
if len(st.session_state.messages) == 0:
    st.markdown("##### 💡 Suggested Questions")
    col1, col2, col3 = st.columns(3)
    
    suggested_prompt = None
    with col1:
        if st.button("📅 Upcoming Deadlines", use_container_width=True):
            suggested_prompt = "What are my upcoming course deadlines this week, and what should I prioritize?"
    with col2:
        if st.button("🔄 Class Schedule", use_container_width=True):
            suggested_prompt = "Can you summarize my class schedule for the next two weeks, including any make-up classes or cancellations?"
    with col3:
        if st.button("📝 Reminder", use_container_width=True):
            suggested_prompt = "Can you remind me of any important tasks or assignments I need to complete soon?"

    if suggested_prompt:
        st.session_state.messages.append({"role": "user", "content": suggested_prompt})
        st.rerun()

# Chat Input from user
if prompt := st.chat_input("Ask Gemini anything..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()

# If the last message in history is from user, generate assistant streaming response!
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    user_prompt = st.session_state.messages[-1]["content"]
    
    with st.chat_message("assistant"):
        if "chat" not in st.session_state:
            init_chat_session()

        try:
            def stream_generator():
                try:
                    for chunk in st.session_state.chat.send_message_stream(user_prompt):
                        if chunk.text:
                            yield chunk.text
                except Exception as stream_err:
                    err_str = str(stream_err).lower()
                    # Auto-recover if client was closed, rate limited, or model error -> try fallback model
                    if "closed" in err_str or "not_found" in err_str or "429" in err_str or "resource" in err_str:
                        fallback_model = ALTERNATIVE_MODEL if st.session_state.get("active_model") == PRIMARY_MODEL else PRIMARY_MODEL
                        recovered_chat = init_chat_session(model_name=fallback_model)
                        for chunk in recovered_chat.send_message_stream(user_prompt):
                            if chunk.text:
                                yield chunk.text
                    else:
                        raise stream_err

            full_response = st.write_stream(stream_generator())
            st.session_state.messages.append({"role": "assistant", "content": full_response})
        except Exception as e:
            err_msg = f"Error generating response: {e}"
            st.error(err_msg)
            st.session_state.messages.append({"role": "assistant", "content": err_msg})
