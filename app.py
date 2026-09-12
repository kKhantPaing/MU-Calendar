import os
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
import streamlit as st
from google import genai
from google.genai import types
from gemini_export import get_calendar_export

# Load environment variables from .env file if present
load_dotenv()

st.set_page_config(
    page_title="Gemini Chat Assistant",
    page_icon="✨",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------
# Configuration & Context
# ---------------------------------------------------------
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

# Model & Generation Settings
PRIMARY_MODEL = "gemini-3.5-flash-lite"
ALTERNATIVE_MODEL = "gemini-3.1-flash-lite"
selected_model = PRIMARY_MODEL
temperature = 0.7

current_dir = os.path.dirname(os.path.abspath(__file__))

# Course JSON files to load alongside the calendar export
COURSE_JSON_FILES = ["ITCS544.json", "ITCS503.json", "ITCS509.json", "ITCS525.json"]
CUSTOM_UPDATE_FILE = "CustomUpdate.json"
custom_update_path = os.path.join(current_dir, CUSTOM_UPDATE_FILE)
custom_mtime = os.path.getmtime(custom_update_path) if os.path.exists(custom_update_path) else 0.0


def normalize_course_code(code_str: Any, known_codes: List[str]) -> str:
    """
    Normalizes course code representations (e.g. '691_ITCS503', 'ITCS 503', '503')
    to standard project course codes (e.g. 'ITCS503').
    """
    if not code_str:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(code_str)).upper()
    for kc in known_codes:
        kc_clean = re.sub(r"[^A-Za-z0-9]", "", kc).upper()
        if kc_clean == cleaned or kc_clean in cleaned or cleaned in kc_clean:
            return kc
    nums = re.findall(r"\d{3}", str(code_str))
    if nums:
        for kc in known_codes:
            if nums[0] in kc:
                return kc
    return str(code_str).strip()


def load_custom_updates_data(file_path: str) -> List[Dict[str, Any]]:
    """
    Safely reads CustomUpdate.json and returns a list of update dictionaries.
    Supports list, wrapped schedules object, or course-keyed objects.
    """
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return []
            raw = json.loads(content)
    except Exception as e:
        print(f"Warning: failed to read {file_path}: {e}")
        return []

    updates: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        updates = [item for item in raw if isinstance(item, dict)]
    elif isinstance(raw, dict):
        if "schedules" in raw and isinstance(raw["schedules"], list):
            updates = [item for item in raw["schedules"] if isinstance(item, dict)]
        elif "date" in raw:
            updates = [raw]
        else:
            for k, val in raw.items():
                if k == "metadata":
                    continue
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            if "course" not in item:
                                item["course"] = k
                            updates.append(item)
                elif isinstance(val, dict):
                    if "course" not in val:
                        val["course"] = k
                    updates.append(val)
    return updates


def apply_custom_updates(
    course_schedules: Dict[str, Any], custom_updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Overwrites or appends schedule entries in course_schedules with highest priority.
    Returns list of successfully applied override entries.
    """
    applied: List[Dict[str, Any]] = []
    if not custom_updates:
        return applied

    for update in custom_updates:
        raw_course = update.get("course", "")
        target_code = normalize_course_code(raw_course, list(course_schedules.keys()))
        if not target_code:
            target_code = raw_course if raw_course else "CUSTOM"

        if target_code not in course_schedules:
            course_schedules[target_code] = {
                "metadata": {
                    "course_code": target_code,
                    "course_name": update.get("course_full_name", target_code),
                    "source": "Manual CustomUpdate.json",
                    "timezone": "Asia/Bangkok (UTC+7)",
                },
                "schedules": [],
            }

        schedules = course_schedules[target_code].setdefault("schedules", [])
        target_date = str(update.get("date", "")).strip()
        target_start = str(update.get("start_time", "")).strip()
        target_week = update.get("week")

        # Find candidate matching sessions in existing course schedules
        candidates = []
        for s in schedules:
            s_date = str(s.get("date", "")).strip()
            if target_date and s_date == target_date:
                candidates.append(s)
            elif not target_date and target_week is not None and s.get("week") == target_week:
                candidates.append(s)

        if candidates:
            matched = None
            if len(candidates) == 1:
                matched = candidates[0]
            else:
                # Disambiguate by start_time, topic, or type
                if target_start:
                    for c in candidates:
                        if str(c.get("start_time", "")).strip() == target_start:
                            matched = c
                            break
                if not matched and "topic" in update:
                    for c in candidates:
                        if update["topic"].lower() in str(c.get("topic", "")).lower():
                            matched = c
                            break
                if not matched and "type" in update:
                    for c in candidates:
                        if update["type"].lower() in str(c.get("type", "")).lower():
                            matched = c
                            break
                matched = matched or candidates[0]

            # Highest priority: overwrite existing fields with custom update values
            for k, v in update.items():
                if v is not None and v != "":
                    matched[k] = v
            matched["_custom_override"] = True
            applied.append(matched)
        else:
            # New entry - append as new session
            new_entry = dict(update)
            new_entry["_custom_override"] = True
            if "course_full_name" not in new_entry:
                new_entry["course_full_name"] = course_schedules[target_code].get(
                    "metadata", {}
                ).get("course_name", target_code)
            if "summary" not in new_entry:
                topic_str = new_entry.get("topic", new_entry.get("type", "Class"))
                new_entry["summary"] = f"{target_code} - [{new_entry.get('type', 'Class')}] {topic_str}"
            schedules.append(new_entry)
            applied.append(new_entry)

        # Keep schedules sorted chronologically by date and start_time
        def sort_key(s: Dict[str, Any]) -> tuple:
            d = s.get("date") or "9999-99-99"
            t = s.get("start_time") or "00:00"
            return (d, t)

        schedules.sort(key=sort_key)

    return applied


# Calendar Data Sync & Loading
@st.cache_data(ttl=300, show_spinner="Syncing latest course calendar...")
def load_calendar_data(custom_file_mtime: float = 0.0) -> Dict[str, Any]:
    # Step 1: Load each course schedule JSON file
    course_schedules: Dict[str, Any] = {}
    for course_file in COURSE_JSON_FILES:
        course_path = os.path.join(current_dir, course_file)
        if os.path.exists(course_path):
            try:
                with open(course_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    course_code = data.get("metadata", {}).get(
                        "course_code", course_file.replace(".json", "")
                    )
                    course_schedules[course_code] = data
            except Exception as e:
                print(f"Warning: failed to load {course_file}: {e}")

    # Step 2: Load and apply manual updates with highest priority
    custom_updates = load_custom_updates_data(custom_update_path)
    applied_overrides = apply_custom_updates(course_schedules, custom_updates)

    # Step 3: Fetch Moodle calendar export in memory
    calendar_export = None
    try:
        calendar_export = get_calendar_export()
    except Exception as e:
        print(f"Warning: failed to fetch calendar data: {e}")

    return {
        "calendar_export": calendar_export,
        "course_schedules": course_schedules,
        "applied_overrides": applied_overrides,
    }


loaded = load_calendar_data(custom_file_mtime=custom_mtime)
calendar_data = loaded.get("calendar_export")
course_schedules = loaded.get("course_schedules", {})
applied_custom_updates = loaded.get("applied_overrides", [])
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

    # Inject high-priority manual overrides if present
    if applied_custom_updates:
        system_instruction += f"""
## MANUAL SCHEDULE UPDATES & OVERRIDES (HIGHEST PRIORITY)
The following update(s) were manually entered in CustomUpdate.json and have the HIGHEST PRIORITY.
CRITICAL INSTRUCTION: When answering queries about classes, times, delivery modes, or cancellations, these manual updates STRICTLY OVERWRITE AND SUPERSEDE any contradictory information in the course syllabus or Moodle calendar:
{json.dumps(applied_custom_updates, indent=2)}
"""

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
- HIGHEST PRIORITY: Always prioritize manual updates from CustomUpdate.json above all else.
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


def get_chat_history_contents() -> List[types.Content]:
    history = []
    for m in st.session_state.messages:
        if m.get("content"):
            role = "model" if m["role"] == "assistant" else "user"
            history.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=m["content"])],
                )
            )
    return history


def init_chat_session(model_name: Optional[str] = None):
    if not api_key:
        return None
    st.session_state.client = genai.Client(api_key=api_key)
    st.session_state.current_api_key = api_key
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
    )
    existing_history = get_chat_history_contents() if st.session_state.messages else None
    if existing_history and existing_history[-1].role == "user":
        existing_history.pop()

    target_model = model_name or selected_model
    try:
        st.session_state.chat = st.session_state.client.chats.create(
            model=target_model,
            config=config,
            history=existing_history if existing_history else None,
        )
        st.session_state.active_model = target_model
    except Exception:
        # Fallback to alternative model if primary fails
        fallback_model = ALTERNATIVE_MODEL if target_model == PRIMARY_MODEL else PRIMARY_MODEL
        st.session_state.chat = st.session_state.client.chats.create(
            model=fallback_model,
            config=config,
            history=existing_history if existing_history else None,
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
    st.title("✨ Gemini Chat Assistant")
    n_courses = len(course_schedules)
    n_overrides = len(applied_custom_updates)
    override_badge = f" • ⚡ {n_overrides} manual override{'s' if n_overrides > 1 else ''}" if n_overrides > 0 else ""
    if n_courses > 0 and calendar_data:
        status_badge = f"📅 {n_courses} courses{override_badge} + calendar loaded"
    elif n_courses > 0:
        status_badge = f"📚 {n_courses} course schedules{override_badge} loaded"
    elif calendar_data:
        status_badge = f"📅 Calendar loaded{override_badge}"
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
    st.error(
        "⚠️ No Gemini API key found in `.streamlit/secrets.toml`. "
        "Please add `gemini_api_key = \"...\"` to your secrets file."
    )
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
        if st.button("🔄 Class Schedule & Make-ups", use_container_width=True):
            suggested_prompt = "What classes are cancelled, and what make-up classes do I need to attend?"
    with col3:
        if st.button("📝 Study Schedule Plan", use_container_width=True):
            suggested_prompt = "Create a day-by-day study schedule for this week leading up to my deadlines."

    if suggested_prompt:
        st.session_state.messages.append({"role": "user", "content": suggested_prompt})
        st.rerun()

# Chat Input from user
if prompt := st.chat_input("Ask Gemini anything..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()

# Assistant streaming response
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
                    # Auto-recover if rate limited, closed, or model error -> try fallback model
                    if any(k in err_str for k in ("closed", "not_found", "429", "resource")):
                        fallback_model = (
                            ALTERNATIVE_MODEL
                            if st.session_state.get("active_model") == PRIMARY_MODEL
                            else PRIMARY_MODEL
                        )
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
