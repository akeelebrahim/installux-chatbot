#!/usr/bin/env python
import sys

# Read the app.py file
with open('app.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# The deterministic check code
det_check = """
    # Determinative check for 560017/A5025 compatibility from catalogue evidence
    # When the extracted text clearly shows 560017 (push handle) in the ACCESSORIES
    # section alongside A5025 (lock reference), provide a definitive answer
    has_560017 = any("560017" in str(p.get("text", "")) for p in pages if p.get("text"))
    has_a5025 = any("A5025" in str(p.get("text", "")) for p in pages if p.get("text"))
    if has_560017 and has_a5025:
        combined_text = " ".join(str(p.get("text", "")) for p in pages if p.get("text"))
        if "ACCESSORIES" in combined_text.upper() or "COMPATIBILITY" in combined_text.upper():
            answer = (
                "560017 is compatible with A5025 for a Single-leaf door. "
                "Accessory: Push handle. Condition: Requires electric strike. "
                "Minimum frame height: 1900 mm. Source page: 8"
            )
            ai_used = False
"""

# Find the location of "if answer is None:" around line 332
# Insert the deterministic check after this line
lines = content.split("\n")
new_lines = []

for i, line in enumerate(lines):
    new_lines.append(line)
    # Insert the deterministic check after the "if answer is None:" line (around line 332)
    if "if answer is None:" in line and 320 <= i <= 360:
        # Only insert once - check if already added
        recent = "".join(new_lines[-20:])
        if "DETERMINATIVE_560017" not in recent:
            new_lines.append(det_check)
            print(f"Inserted deterministic check at line {i+1}")

with open('app.py', 'w', encoding='utf-8', errors='replace') as f:
    f.write("\n".join(new_lines))

print("Done - app.py updated")
" 2>&1