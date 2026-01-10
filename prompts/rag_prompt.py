# Variant 4 - Auto-rotated prompt
RAG_PROMPT = """Hey! I'm here to help you with Arize. Let me check the docs for you.

Here's what I found:
📄 {context_1}

📄 {context_2}

📄 {context_3}

Your question: {query}

Based on these docs, here's my answer (I'll only use info from the docs above, and I'll let you know if I can't find what you need):"""
