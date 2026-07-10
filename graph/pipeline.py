"""
pipeline.py — L'Ingénieur Système (Le Câblage)

Atelier d'assemblage final : instancie le StateGraph, câble les nœuds
(nodes.py) et les aiguilleurs (router.py) autour du State commun
(state.py), puis compile. `app` est l'objet final importé par FastAPI.
"""
from langgraph.graph import END, START, StateGraph

from graph.nodes import narration_node, rag_node, scraper_node
from graph.router import should_scrape_or_narrate
from graph.state import AgentState

workflow = StateGraph(AgentState)

workflow.add_node("rag", rag_node)
workflow.add_node("scraper", scraper_node)
workflow.add_node("narration", narration_node)

workflow.add_edge(START, "rag")
workflow.add_conditional_edges(
    "rag",
    should_scrape_or_narrate,
    {"scraper": "scraper", "narration": "narration"},
)
workflow.add_edge("scraper", "narration")
workflow.add_edge("narration", END)

app = workflow.compile()


if __name__ == "__main__":
    import asyncio
    import logging

    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    async def _smoke_test():
        for question in [
            "Parle-moi de Shining",
            "Raconte-moi tout sur un film d'horreur totalement obscur et inconnu du jury",
        ]:
            print(f"\n=== {question} ===")
            result = await app.ainvoke(
                {"user_question": question, "messages": [], "tools_used": []}
            )
            print(f"rag_sufficient : {result['rag_sufficient']}")
            print(f"tools_used     : {result['tools_used']}")
            print(f"réponse        : {result['messages'][-1].content[:300]}")

    asyncio.run(_smoke_test())
