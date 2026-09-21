import sys
import os
import json
import re
from datetime import datetime

def validate_time(t_str):
    if not isinstance(t_str, str):
        return False, "Time must be a string (e.g. '09:00')"
    t_str = t_str.strip()
    if not t_str:
        return True, None
    if not re.match(r'^\d{2}:\d{2}$', t_str):
        return False, f"Invalid time format '{t_str}'. Expected 'HH:MM' (24-hour format, e.g. '09:00')"
    hours, minutes = map(int, t_str.split(':'))
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return False, f"Invalid time values '{t_str}'. Hours must be 00-23, minutes 00-59"
    return True, None

def validate_date(d_str):
    if not isinstance(d_str, str):
        return False, "Date must be a string (e.g. '2026-09-13')"
    d_str = d_str.strip()
    if not d_str:
        return False, "Date cannot be empty"
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', d_str):
        return False, f"Invalid date format '{d_str}'. Expected 'YYYY-MM-DD'"
    try:
        datetime.strptime(d_str, "%Y-%m-%d")
    except ValueError as e:
        return False, f"Invalid calendar date '{d_str}': {e}"
    return True, None

def validate_custom_update_file(file_path):
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        print(f"Notice: {file_path} is empty. (Valid: no overrides applied)")
        return True

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"JSON Syntax Error in {file_path} (line {e.lineno}, col {e.colno}): {e.msg}")
        return False

    # Extract items into a flat list for validation
    entries = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        if "schedules" in data:
            if not isinstance(data["schedules"], list):
                print("Error: 'schedules' key must contain a list of entries.")
                return False
            entries = data["schedules"]
        elif "date" in data:
            entries = [data]
        else:
            for course_key, items in data.items():
                if course_key == "metadata":
                    continue
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict) and "course" not in it:
                            it["course"] = course_key
                        entries.append(it)
                elif isinstance(items, dict):
                    if "course" not in items:
                        items["course"] = course_key
                    entries.append(items)
                else:
                    print(f"Error: Unexpected value for course '{course_key}'. Expected list or dict.")
                    return False
    else:
        print(f"Error: Root JSON must be an array or object, got {type(data).__name__}.")
        return False

    errors = []
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"Entry #{idx}: Expected object/dict, got {type(entry).__name__}")
            continue

        # Check 'course' (e.g. 'ITCS 509', 'ITCS 503')
        course = entry.get("course")
        if not course or not isinstance(course, str) or not course.strip():
            errors.append(f"Entry #{idx}: Missing or invalid 'course' field (e.g. 'ITCS 509')")

        # Check 'week'
        week_val = entry.get("week")
        if week_val is not None and not isinstance(week_val, int):
            try:
                int(week_val)
            except (ValueError, TypeError):
                errors.append(f"Entry #{idx}: 'week' must be an integer or null (e.g. 5)")

        # Check 'date'
        date_val = entry.get("date")
        if date_val is not None:
            is_valid, msg = validate_date(date_val)
            if not is_valid:
                errors.append(f"Entry #{idx}: {msg}")
        else:
            if "week" not in entry or entry.get("week") is None:
                errors.append(f"Entry #{idx}: Either 'date' (YYYY-MM-DD) or 'week' must be provided")

        # Check 'start_time'
        start_val = entry.get("start_time")
        if start_val is not None:
            is_valid, msg = validate_time(start_val)
            if not is_valid:
                errors.append(f"Entry #{idx}: {msg}")

        # Check 'end_time'
        end_val = entry.get("end_time")
        if end_val is not None:
            is_valid, msg = validate_time(end_val)
            if not is_valid:
                errors.append(f"Entry #{idx}: {msg}")

        # Check string fields: type, delivery_mode, topic, course_full_name, summary
        for str_field in ["type", "delivery_mode", "topic", "course_full_name", "summary"]:
            val = entry.get(str_field)
            if val is not None and not isinstance(val, str):
                errors.append(f"Entry #{idx}: '{str_field}' must be a string")

    if errors:
        print(f"\n[FAIL] Validation failed for {file_path} ({len(errors)} error(s) found):")
        for err in errors:
            print(f"  - {err}")
        return False

    print(f"\n[PASS] Validation passed: {file_path} is correctly formatted ({len(entries)} entry/entries verified).")
    for idx, entry in enumerate(entries, start=1):
        wk_part = f"Week {entry.get('week')} | " if entry.get("week") is not None else ""
        start_t = entry.get("start_time")
        end_t = entry.get("end_time")
        time_part = f" | {start_t}-{end_t}" if start_t and end_t else (f" | {start_t}" if start_t else "")
        topic = f" | {entry.get('topic')}" if entry.get("topic") else ""
        print(f"  [{idx}] {wk_part}{entry.get('course')} | {entry.get('date')}{time_part} | [{entry.get('type', '')}]{topic}")
    return True

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    target = sys.argv[1] if len(sys.argv) > 1 else "CustomUpdate.json"
    success = validate_custom_update_file(target)
    sys.exit(0 if success else 1)
