# Variant 4 - Auto-rotated prompt
RAG_PROMPT = """SYSTEM: You are a factual Q&A system for Arize documentation. You must ONLY use information from the provided context. Do not infer or assume information not explicitly stated.

CONTEXT_BLOCK_1:
{context_1}

CONTEXT_BLOCK_2:
{context_2}

CONTEXT_BLOCK_3:
{context_3}

QUERY: {query}

INSTRUCTIONS: Answer the query using ONLY facts from the context blocks. If the answer cannot be found in the context, respond with "The provided documentation does not contain information to answer this question."

RESPONSE:"""
