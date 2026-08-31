#!/usr/bin/env python3
import search

print(f'is_reference_query("10230A"): {search.is_reference_query("10230A")}')

# Check ref_candidates
near = search.ref_candidates('10230A', limit=8)
print(f'ref_candidates: {near}')

# Check find_ref_in_question
exact = search.find_ref_in_question('10230A')
print(f'find_ref_in_question: {exact}')