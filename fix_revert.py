import pathlib
p=pathlib.Path('app.py')
lines=p.read_text(encoding='utf-8').split('\n')
# Find def ask
start=None
end=None
for i,l in enumerate(lines):
    if l.startswith('def ask(req: AskRequest):'):
        start=i
    if start is not None and l.strip().startswith('except Exception as e:') and i>start:
        end=i
        break
if start is not None and end is not None:
    # Find try line
    try_idx = None
    for i in range(start, end):
        if lines[i].strip() == 'try:':
            try_idx=i
            break
    if try_idx is not None:
        # Remove try line and except block (3 lines: except, log, return)
        # Dedent lines between try+1 and except-1 by 4 spaces
        new_lines=[]
        for i,l in enumerate(lines):
            if i==try_idx:
                continue
            if try_idx < i < end:
                # dedent by 4 if starts with 8 spaces -> 4, etc.
                if l.startswith('        '): # 8 -> 4
                    # But need to handle 12 -> 8 etc.
                    # Remove 4 leading spaces
                    new_lines.append(l[4:])
                elif l.startswith('    '):
                    # shouldn't happen inside try, but handle
                    new_lines.append(l)
                else:
                    new_lines.append(l)
            elif i>=end and i<=end+1: # except and following 2 lines
                # skip except block (3 lines)
                if i==end or i==end+1:
                    continue
                # the return line after except is at line end+1? Actually we have 2 lines after except
                # Let's skip 2 lines after except
                continue
            else:
                # need to handle the second line after except (return JSONResponse) which is at end+1
                # We already skipped, but need to skip the next line too
                if i==end+1:
                    continue
                new_lines.append(l)
        # The above logic missed the second line after except (the return)
        # Let's just reconstruct by removing try and except block properly
        # Simpler: re-read and manually fix
        pass

# Simpler: restore from previous version by removing try indentation
# Let's just rewrite the ask function from scratch using known good version
# We'll replace the whole ask function with a clean version without try

import re
t=p.read_text(encoding='utf-8')
# Remove the try we added (with extra indent) and except
# Use regex to find the malformed block
pattern = r"def ask\(req: AskRequest\):\n    try:\n(.*?)\n    except Exception as e:\n        log\.exception.*?\n        return JSONResponse.*?\n"
m=re.search(pattern, t, re.DOTALL)
if m:
    body=m.group(1)
    # dedent body by 4 spaces (remove the extra indent we added)
    dedented=[]
    for line in body.split('\n'):
        if line.startswith('        '):
            dedented.append(line[4:])
        else:
            dedented.append(line)
    new_body="\n".join(dedented)
    t=t.replace(m.group(0), f"def ask(req: AskRequest):\n{new_body}\n")
    p.write_text(t, encoding='utf-8')
    print("fixed revert")
else:
    print("pattern not found")
    # debug
    import pathlib as pl
    print(t[ t.find('def ask'): t.find('def ask')+800][:800])
