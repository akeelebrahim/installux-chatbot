import requests

# Test French to English translation
r = requests.post('http://127.0.0.1:8509/api/ask', json={'question': 'porte coulissante avec charniere 560032'}, timeout=15)
d = r.json()
print("Question:", d.get('question'))
print("Answer:", d.get('answer', '')[:500] if d else 'none')
print("AI used:", d.get('ai_used'))
print("Clarify:", d.get('clarify'))