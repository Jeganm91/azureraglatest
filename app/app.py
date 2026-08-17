import json
import time
import uuid
import logging

from flask import Flask, request, session, render_template, redirect, url_for
import requests
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

import config

app = Flask(__name__)
app.secret_key = "lab-secret-key-change-me"

runtime_state = {
    "retrieval_config": dict(config.DEFAULT_RETRIEVAL_CONFIG),
    "system_prompt": config.DEFAULT_SYSTEM_PROMPT,
    "memory_enabled": config.DEFAULT_MEMORY_ENABLED,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rag-app")


def get_openai_client():
    if not config.AZURE_OPENAI_ENDPOINT or not config.AZURE_OPENAI_API_KEY:
        return None
    return AzureOpenAI(
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        api_key=config.AZURE_OPENAI_API_KEY,
        api_version=config.AZURE_OPENAI_API_VERSION,
    )


def get_search_client():
    if not config.AZURE_SEARCH_ENDPOINT or not config.AZURE_SEARCH_API_KEY:
        return None
    return SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_API_KEY),
    )


def get_embedding(text: str):
    client = get_openai_client()
    if not client:
        return []
    try:
        res = client.embeddings.create(
            input=text,
            model=config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
        )
        return res.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return []


def call_mcp_tool(query: str):
    try:
        resp = requests.post(
            f"{config.MCP_SERVER_URL}/tools/get_latest_policy",
            json={"query": query},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def should_use_mcp(query: str) -> bool:
    triggers = ["latest", "current version", "most recent", "up to date", "up-to-date"]
    q = query.lower()
    return any(t in q for t in triggers)


def retrieve_azure_search(query_text: str, top_k: int, search_type: str, rerank: bool):
    search_client = get_search_client()
    if not search_client:
        return []

    results_list = []
    try:
        if search_type in ["VECTOR", "HYBRID"]:
            emb = get_embedding(query_text)
            vector_query = VectorizedQuery(vector=emb, k_nearest_neighbors=top_k, fields="vector") if emb else None
            
            search_args = {
                "search_text": query_text if search_type == "HYBRID" else None,
                "select": ["id", "title", "content", "source_file", "version", "status"],
                "top": top_k
            }
            if vector_query:
                search_args["vector_queries"] = [vector_query]
            if rerank:
                search_args["query_type"] = "semantic"
                search_args["semantic_configuration_name"] = "default-semantic-config"

            results = search_client.search(**search_args)
        else:
            results = search_client.search(
                search_text=query_text,
                select=["id", "title", "content", "source_file", "version", "status"],
                top=top_k
            )

        for doc in results:
            results_list.append({
                "content": doc.get("content", ""),
                "source": doc.get("source_file", doc.get("title", "unknown")),
                "score": doc.get("@search.score", 0.0),
                "status": doc.get("status", ""),
                "version": doc.get("version", "")
            })
    except Exception as e:
        logger.error(f"Search retrieval error: {e}")
    return results_list


def run_rag_query(user_query: str, session_id: str, memory_enabled: bool, history_turns=None):
    t0 = time.time()
    rc = runtime_state["retrieval_config"]

    mcp_result = None
    if should_use_mcp(user_query):
        mcp_result = call_mcp_tool(user_query)

    citations = retrieve_azure_search(
        query_text=user_query,
        top_k=int(rc.get("number_of_results", 4)),
        search_type=rc.get("search_type", "HYBRID"),
        rerank=rc.get("reranking_enabled", False)
    )

    formatted_context = ""
    for c in citations:
        formatted_context += f"--- Source: {c['source']} (Status: {c.get('status', 'N/A')}) ---\n{c['content']}\n\n"

    if mcp_result and "error" not in mcp_result:
        formatted_context += f"--- Tool Output (MCP) ---\n{json.dumps(mcp_result, indent=2)}\n"

    system_prompt = runtime_state["system_prompt"]
    prompt_with_context = system_prompt.replace("$search_results$", formatted_context).replace("$query$", user_query)

    messages = [{"role": "system", "content": prompt_with_context}]

    if memory_enabled and history_turns:
        for turn in history_turns[-5:]:
            if "query" in turn and "answer" in turn and turn["answer"]:
                messages.append({"role": "user", "content": turn["query"]})
                messages.append({"role": "assistant", "content": turn["answer"]})

    messages.append({"role": "user", "content": user_query})

    openai_client = get_openai_client()
    answer = None
    error = None

    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=messages,
                temperature=0.0
            )
            answer = response.choices[0].message.content
        except Exception as e:
            error = str(e)
    else:
        error = "Azure OpenAI credentials not configured. Please check config.py"

    latency_ms = int((time.time() - t0) * 1000)

    result = {
        "query": user_query,
        "answer": answer,
        "citations": citations,
        "session_id": session_id,
        "mcp_used": mcp_result is not None,
        "mcp_result": mcp_result,
        "latency_ms": latency_ms,
        "error": error,
    }
    return result


@app.route("/", methods=["GET"])
def index():
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    history = session.get("history", [])
    return render_template("index.html", history=history, state=runtime_state)


@app.route("/query", methods=["POST"])
def query():
    user_query = request.form.get("query", "").strip()
    if not user_query:
        return redirect(url_for("index"))

    session_id = session.get("session_id", str(uuid.uuid4()))
    session["session_id"] = session_id

    history = session.get("history", [])
    result = run_rag_query(user_query, session_id, runtime_state["memory_enabled"], history)

    history.append(result)
    session["history"] = history[-10:]

    return render_template("index.html", history=session["history"], state=runtime_state)


@app.route("/reset", methods=["POST"])
def reset():
    session["history"] = []
    session["session_id"] = str(uuid.uuid4())
    return redirect(url_for("index"))


@app.route("/config", methods=["GET", "POST"])
def config_panel():
    if request.method == "POST":
        runtime_state["retrieval_config"]["search_type"] = request.form.get(
            "search_type", "HYBRID"
        )
        runtime_state["retrieval_config"]["number_of_results"] = int(
            request.form.get("number_of_results", 4)
        )
        runtime_state["retrieval_config"]["reranking_enabled"] = (
            request.form.get("reranking_enabled") == "on"
        )
        runtime_state["memory_enabled"] = request.form.get("memory_enabled") == "on"
        runtime_state["system_prompt"] = request.form.get(
            "system_prompt", runtime_state["system_prompt"]
        )
        return redirect(url_for("config_panel"))

    return render_template("config.html", state=runtime_state)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)