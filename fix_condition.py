#!/usr/bin/env python3
import os

filepath = r'C:\Users\PC\Documents\Default Project\Installux-ChatBot\app.py'

with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find and replace the weight check code to add 'and answer is None'
# The current code has: if is_560032_weight_query:
# We need to change it to: if is_560032_weight_query and answer is None:

# First find the position
idx = content.find('if is_560032_weight_query:')
if idx != -1:
    # Find the end of this line
    line_end = content.find('\n', idx)
    # Replace just the condition line
    new_line = '    if is_560032_weight_query and answer is None:'
    new_content = content[:idx] + new_line + content[line_end:]
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Replaced condition successfully')
else:
    print('Could not find the condition line')