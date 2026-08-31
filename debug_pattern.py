question = "What is the maximum leaf weight for hinge 560032 on a 900 x 2000 mm door?"
question_lower = question.lower()

has_560032 = "560032" in question_lower
has_weight = "weight" in question_lower
has_kg = "kg" in question_lower
has_leaf = "leaf" in question_lower

print(f"has_560032: {has_560032}")
print(f"has_weight: {has_weight}")
print(f"has_kg: {has_kg}")
print(f"has_leaf: {has_leaf}")

is_560032_weight_query = has_560032 and (has_weight or has_kg or has_leaf)
print(f"\nis_560032_weight_query: {is_560032_weight_query}")

# Test the condition logic
ai_used = False
cond1 = ai_used is None
cond2 = ai_used != False
print(f"\n ai_used = {ai_used}")
print(f" ai_used is None: {cond1}")
print(f" ai_used != False: {cond2}")
result = cond1 or cond2
print(f" condition (ai_used is None or ai_used != False): {result}")