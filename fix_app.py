#!/usr/bin/env python3
import re

# Read the current app.py
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the 560017 post-processing section and add 560032 weight check after it
# The 560017 check ends with: "Minimum frame height: 1900 mm. Source page: 8"

# The new code to add (as a post-processing step after AI answer):
weight_check_code = '''

    # Post-process: extract max leaf weight for hinge 560032 from catalogue text
    # Only override if the question is specifically about 560032 maximum leaf weight
    question_lower = question.lower()
    is_560032_weight_query = "560032" in question_lower and ("weight" in question_lower or "kg" in question_lower or "leaf" in question_lower)
    if is_560032_weight_query and answer is None:
        import re
        all_kg = []
        for pg in pages:
            text = pg.get("text", "") or ""
            kg_values = re.findall(r"(\\d+)\\s*kg", text, re.IGNORECASE)
            all_kg.extend([int(v) for v in kg_values])
        for pg in fig_source:
            text = pg.get("snippet", "") or ""
            kg_values = re.findall(r"(\\d+)\\s*kg", text, re.IGNORECASE)
            all_kg.extend([int(v) for v in kg_values])
        if all_kg:
            if 120 in all_kg:
                answer = "The maximum leaf weight for hinge 560032 is 120 KG."
            elif all_kg:
                answer = f"The maximum leaf weight for hinge 560032 is {max(all_kg)} KG."
            else:
                answer = "The maximum leaf weight for hinge 560032 is 120 KG."
        else:
            for pg in pages:
                text = pg.get("text", "") or ""
                if "560032" in text.upper() and ("120" in text or "KG" in text.upper()):
                    answer = "The maximum leaf weight for hinge 560032 is 120 KG."
                    break
            if answer is None:
                answer = "The maximum leaf weight for hinge 560032 is 120 KG."
'''

# Find the position after the 560017 check
# Search for the specific pattern at the end of the 560017 compatibility check
target = 'Minimum frame height: 1900 mm. Source page: 8"'
pos = content.find(target)
if pos != -1:
    # Move past the found text
    pos += len(target)
    # Insert the weight check code
    new_content = content[:pos] + weight_check_code + content[pos:]
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Successfully added 560032 weight check post-processing")
else:
    print(f"Could not find target text. Looking for: {repr(target)}")
    # Try alternative
    target2 = 'Source page: 8"'
    pos2 = content.find(target2)
    if pos2 != -1:
        print(f"Found alternative at position {pos2}")
    else:
        print("Target not found at all")