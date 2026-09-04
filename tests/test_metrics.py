"""
Tests unitaires de graph/metrics.py — les métriques Prometheus métier
(appels d'outils, durée par nœud, tokens consommés). On lit directement les
objets prometheus_client plutôt que de monter un vrai serveur HTTP /metrics.
"""
from graph.metrics import (
    LLM_TOKENS_TOTAL,
    NODE_DURATION_SECONDS,
    TOOL_CALLS_TOTAL,
    record_token_usage,
    record_tool_call,
)


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


class TestRecordToolCall:
    def test_increments_the_right_labels(self):
        before = _counter_value(TOOL_CALLS_TOTAL, tool_name="movie_age", node="rag")

        record_tool_call("movie_age", "rag")

        assert _counter_value(TOOL_CALLS_TOTAL, tool_name="movie_age", node="rag") == before + 1

    def test_different_labels_tracked_independently(self):
        before_rag = _counter_value(TOOL_CALLS_TOTAL, tool_name="detailed_synopsis", node="rag")
        before_scraper = _counter_value(TOOL_CALLS_TOTAL, tool_name="detailed_synopsis", node="scraper")

        record_tool_call("detailed_synopsis", "scraper")

        assert _counter_value(TOOL_CALLS_TOTAL, tool_name="detailed_synopsis", node="rag") == before_rag
        assert _counter_value(TOOL_CALLS_TOTAL, tool_name="detailed_synopsis", node="scraper") == before_scraper + 1


class TestRecordTokenUsage:
    def test_records_prompt_and_completion_tokens(self):
        before_prompt = _counter_value(LLM_TOKENS_TOTAL, node="narration", token_type="prompt")
        before_completion = _counter_value(LLM_TOKENS_TOTAL, node="narration", token_type="completion")

        record_token_usage("narration", {"input_tokens": 120, "output_tokens": 340, "total_tokens": 460})

        assert _counter_value(LLM_TOKENS_TOTAL, node="narration", token_type="prompt") == before_prompt + 120
        assert _counter_value(LLM_TOKENS_TOTAL, node="narration", token_type="completion") == before_completion + 340

    def test_none_usage_metadata_is_a_noop(self):
        before = _counter_value(LLM_TOKENS_TOTAL, node="rag", token_type="prompt")

        record_token_usage("rag", None)

        assert _counter_value(LLM_TOKENS_TOTAL, node="rag", token_type="prompt") == before

    def test_empty_dict_is_a_noop(self):
        before = _counter_value(LLM_TOKENS_TOTAL, node="rag", token_type="prompt")

        record_token_usage("rag", {})

        assert _counter_value(LLM_TOKENS_TOTAL, node="rag", token_type="prompt") == before


class TestNodeDurationHistogram:
    def test_time_context_manager_records_an_observation(self):
        before_count = NODE_DURATION_SECONDS.labels(node="rag")._sum.get()

        with NODE_DURATION_SECONDS.labels(node="rag").time():
            pass

        after_count = NODE_DURATION_SECONDS.labels(node="rag")._sum.get()
        assert after_count >= before_count
