"""
Knowledge skill: answers general questions using the local LLM (if Ollama
is running) grounded with a quick free web search, falling back to a plain
web-search summary if no LLM is available.
"""
from friday.utils.logger import get_logger

logger = get_logger(__name__)


def web_search_answer(query: str, web_search) -> str:
    results = web_search.search(query, max_results=3)
    if not results:
        return f"I couldn't find anything online for {query}."
    return f"Here's what I found: {results[0]['summary']}"


def answer_question(question: str, llm_client, web_search) -> str:
    context = ""
    try:
        results = web_search.search(question, max_results=3)
        if results:
            context = "\n".join(f"- {r['summary']}" for r in results)
    except Exception as e:
        logger.warning("Web search failed: %s", e)

    if llm_client.is_available():
        prompt = (
            "You are Friday, a helpful voice assistant. Answer the user's "
            "question in 1-3 short spoken sentences, plainly, with no "
            "markdown formatting.\n\n"
        )
        if context:
            prompt += f"Recent web context:\n{context}\n\n"
        prompt += f"Question: {question}\nAnswer:"

        answer = llm_client.generate(prompt)
        if answer:
            return answer.strip()

    if context:
        return context.split("\n")[0].lstrip("- ").strip()

    return "I'm not able to find an answer for that right now."
