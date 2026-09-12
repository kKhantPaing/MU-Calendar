"""
Mahidol University ICT Moodle Calendar Export Parser
Fetches, parses, and cleans calendar data (.ics) for Gemini Assistant context.
"""

from datetime import datetime, timezone, timedelta
import re
from typing import Any, Dict, Optional
import requests
import streamlit as st

ICT_TIMEZONE = timezone(timedelta(hours=7))


def _extract_ics_field(block: str, name: str) -> str:
    """Extracts a field value from an RFC 5545 VEVENT block."""
    m = re.search(rf'^{name}(?:;[^:]*)?:(.*)$', block, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _parse_ics_datetime(dt_str: str, tz: timezone = ICT_TIMEZONE) -> Optional[datetime]:
    """Parses an iCalendar datetime string into a timezone-aware datetime."""
    if not dt_str:
        return None
    try:
        if dt_str.endswith("Z"):
            return datetime.strptime(dt_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(tz)
        dt = datetime.strptime(dt_str, "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=tz)
    except ValueError:
        return None


def get_calendar_export(url: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetches, parses, and returns cleaned Mahidol University ICT calendar data 
    as a dictionary ready for Gemini context.
    """
    if not url:
        try:
            if "calendar_export_url" in st.secrets:
                url = st.secrets["calendar_export_url"]
            elif "CALENDAR_EXPORT_URL" in st.secrets:
                url = st.secrets["CALENDAR_EXPORT_URL"]
        except Exception:
            pass

    if not url:
        raise ValueError(
            "Calendar export URL not provided. Please set 'calendar_export_url' in .streamlit/secrets.toml."
        )

    # 1. Fetch calendar data (.ics format)
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    calendar_text = response.text

    # 2. Unfold RFC 5545 folded lines (continuation lines starting with space or tab)
    unfolded_text = re.sub(r"\r?\n[ \t]", "", calendar_text)

    # 3. Parse VEVENT blocks
    now_ict = datetime.now(ICT_TIMEZONE)
    events = []

    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", unfolded_text, re.DOTALL):
        start_dt = _parse_ics_datetime(_extract_ics_field(block, "DTSTART"))
        end_dt = _parse_ics_datetime(_extract_ics_field(block, "DTEND"))
        summary = _extract_ics_field(block, "SUMMARY")
        course = _extract_ics_field(block, "CATEGORIES")
        raw_desc = _extract_ics_field(block, "DESCRIPTION")
        desc = raw_desc.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")

        # Categorize event type
        if "[Cancel]" in summary:
            event_type = "Cancelled"
        elif "[Make-up]" in summary:
            event_type = "Make-up"
        elif "due" in summary.lower():
            event_type = "Deadline"
        else:
            event_type = "General"

        # Skip past events
        if end_dt and end_dt < now_ict:
            continue

        events.append({
            "Course": course,
            "Type": event_type,
            "Summary": summary,
            "Start (ICT)": start_dt.strftime("%Y-%m-%d %H:%M") if start_dt else "N/A",
            "End (ICT)": end_dt.strftime("%Y-%m-%d %H:%M") if end_dt else "N/A",
            "Description": desc,
            "_dt": start_dt,
            "_end_dt": end_dt,
        })

    # Sort events chronologically
    min_dt = datetime.min.replace(tzinfo=ICT_TIMEZONE)
    events.sort(key=lambda e: e["_dt"] or min_dt)

    # 4. Generate structured export dict
    gemini_export = {
        "metadata": {
            "source": "Mahidol University ICT Moodle Calendar",
            "timezone": "Asia/Bangkok (UTC+7)",
            "exported_at": now_ict.isoformat(),
        },
        "deadlines": [],
        "class_schedule_adjustments": [],
        "google_calendar_ready_events": [],
    }

    for e in events:
        if e["Type"] == "Deadline":
            gemini_export["deadlines"].append({
                "course": e["Course"],
                "title": e["Summary"],
                "due_datetime": e["Start (ICT)"],
                "details": e["Description"],
            })
            if e["_dt"]:
                dt_str = e["_dt"].strftime("%Y-%m-%d")
                gemini_export["google_calendar_ready_events"].append({
                    "summary": f"[{e['Course']}] {e['Summary']}",
                    "start": {"date": dt_str},
                    "end": {"date": dt_str},
                    "description": e["Description"],
                })

        elif e["Type"] in ("Cancelled", "Make-up"):
            gemini_export["class_schedule_adjustments"].append({
                "course": e["Course"],
                "type": e["Type"],
                "summary": e["Summary"],
                "start": e["Start (ICT)"],
                "end": e["End (ICT)"],
                "details": e["Description"],
            })
            if e["Type"] == "Make-up" and e["_dt"]:
                gemini_export["google_calendar_ready_events"].append({
                    "summary": f"[{e['Course']}] {e['Summary']}",
                    "start": {"dateTime": e["_dt"].isoformat(), "timeZone": "Asia/Bangkok"},
                    "end": {
                        "dateTime": (e["_end_dt"] or e["_dt"]).isoformat(),
                        "timeZone": "Asia/Bangkok",
                    },
                    "description": e["Description"],
                })

    return gemini_export


if __name__ == "__main__":
    data = get_calendar_export()
    print(f"Retrieved {len(data['deadlines'])} deadlines and {len(data['class_schedule_adjustments'])} adjustments.")
