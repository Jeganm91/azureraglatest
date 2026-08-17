import os

# Azure OpenAI settings
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01")
AZURE_OPENAI_CHAT_DEPLOYMENT = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-5-mini")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")

# Azure AI Search settings
AZURE_SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
AZURE_SEARCH_API_KEY = os.environ.get("AZURE_SEARCH_API_KEY", "")
AZURE_SEARCH_INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX_NAME", "policy-knowledge-base")

# MCP Server URL
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:9001")

# Runtime retrieval configuration (editable via /config UI)
DEFAULT_RETRIEVAL_CONFIG = {
    "search_type": "HYBRID",
    "number_of_results": 4,
    "reranking_enabled": True,
}

# Updated prompt: Handles general conversational questions while enforcing policy accuracy & PII safety
DEFAULT_SYSTEM_PROMPT = """You are a helpful, enterprise knowledge and AI assistant.

Instructions:
1. For general greetings, common conversational questions, or basic clarifications (e.g., "Hello", "What can you do?", "Who are you?"), answer helpfully, politely, and concisely.
2. For organizational, technical, or access policy questions:
   - Base your answer primarily on the authoritative CURRENT policy documents in the Context below.
   - Ignore outdated, DEPRECATED, or obsolete policy versions when a CURRENT (v2.0+) version is present.
   - NEVER disclose personally identifiable information (PII) such as phone numbers, employee IDs, personal email addresses, or audit log records. Redact them if referenced.
   - If the specific enterprise policy is not contained in the context, politely state that it is not available in the internal knowledge base.

Context:
$search_results$

User Question: $query$"""

DEFAULT_MEMORY_ENABLED = True