import pathlib, re
p = pathlib.Path('app.py')
t = p.read_text(encoding='utf-8')
# The broken try block: we added "    try:\n        question" but body is still at 4 spaces, should be 8
# Fix by removing the incorrectly added try/except and re-adding correctly
# First, remove the added try and except to restore original
old_try = "def ask(req: AskRequest):\n    try:\n        question = req.question.strip()"
if old_try in t:
    # Find the except we added
    old_except = "    except Exception as e:\n        log.exception(\"ask failed for %r\", question)\n        return JSONResponse({\"error\": f\"Internal Server Error: {e}\"}, status_code=500)"
    # Remove both and restore original without try
    t = t.replace(old_try, "def ask(req: AskRequest):\n    question = req.question.strip()", 1)
    if old_except in t:
        t = t.replace(old_except, "", 1)
    p.write_text(t, encoding='utf-8')
    print("reverted try")
else:
    print("not found try")

# Now add correct try wrapper with proper indentation
# Read again
t = p.read_text(encoding='utf-8')
# Find the ask function body start and end
# We'll wrap the entire body (from question = ... to return {...}) in try
# Find start marker
start_marker = "def ask(req: AskRequest):\n    question = req.question.strip()"
end_marker = "        \"terms\": terms,\n    }"
if start_marker in t and end_marker in t:
    # Extract the body between start_marker and end_marker inclusive
    start_idx = t.find(start_marker)
    end_idx = t.find(end_marker) + len(end_marker)
    body = t[start_idx:end_idx]
    # Now create indented version
    # body currently is from "def ask..." to the return dict
    # We want: def ask...:\n    try:\n        question = ... (8 spaces) ...\n    except...
    # So we need to indent body content by 4 spaces
    lines = body.split('\n')
    # first line is def, second is question line already at 4 spaces
    # For try wrapper, we need:
    # def ask...:
    #     try:
    #         question = ...
    #         ... rest at 8 spaces
    #     except...
    header = lines[0]  # def ask...
    # rest lines from 1 to -1 are the body
    rest = lines[1:]
    # increase indent by 4 for each rest line (if line not empty)
    indented = []
    for line in rest:
        if line.strip() == "":
            indented.append(line)
        else:
            # line currently starts with 4 spaces, make 8
            if line.startswith("    "):
                indented.append("    " + line)
            else:
                indented.append("    " + line)
    new_body = header + "\n    try:\n" + "\n".join(indented) + "\n    except Exception as e:\n        log.exception(\"ask failed for %r\", question)\n        return JSONResponse({\"error\": f\"Internal Server Error: {e}\"}, status_code=500)"
    t = t[:start_idx] + new_body + t[end_idx:]
    p.write_text(t, encoding='utf-8')
    print("added correct try")
else:
    print("markers not found")
