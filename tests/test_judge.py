"""
Tests unitaires de graph/judge.py — Le Juge (évaluation qualité + retry).
LLM entièrement mocké.
"""
from graph.judge import judge_and_retry
from tests.conftest import make_ai_message


class TestJudgeAndRetry:
    def test_valid_verdict_on_first_try_no_retry(self, monkeypatch, fake_llm_factory):
        llm = fake_llm_factory([
            make_ai_message(content='{"is_valid": true, "confidence": 0.9, "reasoning": "ok"}'),
        ])
        monkeypatch.setattr("graph.judge.get_groq_llm", lambda temperature=0.1: llm)

        answer, verdict = judge_and_retry("Question ?", "Réponse initiale.", ["search_horror_movies"])

        assert answer == "Réponse initiale."
        assert verdict["is_valid"] is True
        assert len(llm.invocations) == 1  # aucun retry déclenché

    def test_invalid_low_confidence_triggers_one_retry_then_passes(self, monkeypatch, fake_llm_factory):
        llm = fake_llm_factory([
            make_ai_message(content='{"is_valid": false, "confidence": 0.3, "reasoning": "hallucination"}'),
            make_ai_message(content="Réponse corrigée, sans hallucination."),
            make_ai_message(content='{"is_valid": true, "confidence": 0.9, "reasoning": "bien"}'),
        ])
        monkeypatch.setattr("graph.judge.get_groq_llm", lambda temperature=0.1: llm)

        answer, verdict = judge_and_retry("Question ?", "Réponse bancale.", [])

        assert answer == "Réponse corrigée, sans hallucination."
        assert verdict["is_valid"] is True
        assert len(llm.invocations) == 3

    def test_non_json_response_falls_back_to_default_verdict(self, monkeypatch, fake_llm_factory):
        llm = fake_llm_factory([make_ai_message(content="Ceci n'est pas du JSON.")])
        monkeypatch.setattr("graph.judge.get_groq_llm", lambda temperature=0.1: llm)

        answer, verdict = judge_and_retry("Question ?", "Réponse.", [])

        assert answer == "Réponse."
        assert verdict == {
            "is_valid": True,
            "confidence": 0.75,
            "reasoning": "Évaluation automatique non disponible.",
        }
        assert len(llm.invocations) == 1  # is_valid=True -> pas de retry

    def test_stays_within_max_retries_even_if_still_invalid(self, monkeypatch, fake_llm_factory):
        """Le Juge ne boucle jamais indéfiniment : _MAX_RETRIES=2 tours max."""
        still_invalid = '{"is_valid": false, "confidence": 0.2, "reasoning": "toujours faux"}'
        llm = fake_llm_factory([
            make_ai_message(content=still_invalid),   # évaluation initiale
            make_ai_message(content="Correction 1"),  # retry 1
            make_ai_message(content=still_invalid),   # réévaluation 1
            make_ai_message(content="Correction 2"),  # retry 2
            make_ai_message(content=still_invalid),   # réévaluation 2
        ])
        monkeypatch.setattr("graph.judge.get_groq_llm", lambda temperature=0.1: llm)

        answer, verdict = judge_and_retry("Question ?", "Réponse.", [])

        assert answer == "Correction 2"
        assert verdict["is_valid"] is False
        assert len(llm.invocations) == 5
