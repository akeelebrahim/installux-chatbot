#!/usr/bin/env python3
import re

# Simulate the text extraction from page } 90 kg

# The key issue: the AI needs to extract exact kg values from the text
# Instead of saying "I can't read exact figure", it should extract the values

def extract_kg_values(text):
    """Extract kg values from graph zone text"""
    kg_values = re.findall(r'(\d+)\s*kg', text)
    return [int(v) for v in kg_values]

# Test with page 5 text
page5_text = """MAX. WEIGHT, KG PER LEAF
WITH 2 x THREE-LEAF HINGES
REF. 560032

700 800 900 1000 1100 1200 1300 1800 1900 2000 2100 2200 2300 2400 2500
120 kg
110 kg
90 kg
90 kg
Leaf height (mm)
Leaf width (mm)"""

values = extract_kg_values(page5_text)
print(f'Page 5 kg values: {values}')  # Should be [120, 110, 90, 90]

# Test with page 6 text  
page6_text = """MAX. WEIGHT, KG PER LEAF
WITH 3 x THREE-LEAF HINGES
REF. 560032

700 800 900 1000 1100 1200 1300 1800 1900 2000 2100 2200 2300 2400 2500
150 kg
130 kg
120 kg
80 kg
Leaf height (mm)
Leaf width (mm)"""

values6 = extract_kg_values(page6_text)
print(f'Page 6 kg values: {values6}')  # Should be [150, 130, 120, 80]

# For the question "What is the maximum leaf weight for hinge 560032 on a 900 x 2000 mm door?"
# The answer depends on how many hinges:
# - 2 hinges: max is 120 kg (first zone)
# - 3 hinges: max is 150 kg (first zone), but 120 kg is also a valid zone value

print(f'\nFor 2 hinges: maximum zone value = {max(values)} kg')
print(f'For 3 hinges: maximum zone value = {max(values6)} kg')
print(f'Both contain 120 kg as a zone value')