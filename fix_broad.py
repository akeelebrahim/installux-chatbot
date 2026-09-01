import pathlib
p = pathlib.Path('app.py')
t = p.read_text(encoding='utf-8')
# Wrap the broad block in try/except so Doors never 502
old = "    if search.is_question_broad(question, pages):"
new = "    try:\n        if search.is_question_broad(question, pages):"
if old in t:
    # only replace first occurrence after the 560032 block
    # Find position after _is_out guard to avoid touching other ifs
    idx = t.find(old)
    t = t[:idx] + new + t[idx+len(old):]
    # After the broad return block, add except
    # The broad return ends with '"terms": terms,\n        }\n\n    answer, from_cache'
    target = '                "terms": terms,\n        }\n\n    answer, from_cache'
    repl = '                "terms": terms,\n        }\n    except Exception as _be:\n        import logging\n        logging.getLogger("installux").warning("broad handling failed: %s", _be)\n\n    answer, from_cache'
    if target in t:
        t = t.replace(target, repl, 1)
        p.write_text(t, encoding='utf-8')
        print('patched broad ok')
    else:
        print('broad tail not found')
else:
    print('not found broad head')
