import asyncio
import math
from unittest.mock import AsyncMock, patch

import ragas_client


class TestSafeMean:
    def test_averages_valid_scores(self):
        assert ragas_client.safe_mean([0.8, 0.9, 1.0]) == round(0.9, 4)

    def test_excludes_nan_values(self):
        assert ragas_client.safe_mean([0.8, float("nan"), 1.0]) == round(0.9, 4)

    def test_all_nan_returns_none(self):
        assert ragas_client.safe_mean([float("nan"), float("nan")]) is None

    def test_empty_list_returns_none(self):
        assert ragas_client.safe_mean([]) is None

    def test_rounds_to_4_decimal_places(self):
        values = [0.123456789, 0.987654321]
        assert ragas_client.safe_mean(values) == round(sum(values) / len(values), 4)


class TestSampleCount:
    def test_counts_all_valid_scores(self):
        assert ragas_client.sample_count([0.8, 0.9, 1.0]) == 3

    def test_excludes_nan_values_from_count(self):
        assert ragas_client.sample_count([0.8, float("nan"), 1.0]) == 2

    def test_all_nan_returns_zero(self):
        assert ragas_client.sample_count([float("nan"), float("nan")]) == 0

    def test_empty_list_returns_zero(self):
        assert ragas_client.sample_count([]) == 0


class TestSummarizeScores:
    def test_happy_path_averages_and_counts(self):
        scores = {
            "faithfulness": [0.8, 0.9, 1.0],
            "answer_relevancy": [0.5, 0.7],
        }

        metrics, sample_counts = ragas_client.summarize_scores(scores)

        assert metrics == {
            "faithfulness": ragas_client.safe_mean([0.8, 0.9, 1.0]),
            "answer_relevancy": ragas_client.safe_mean([0.5, 0.7]),
        }
        assert sample_counts == {"faithfulness": 3, "answer_relevancy": 2}

    def test_partial_nan_excluded_from_mean_and_count(self):
        scores = {"faithfulness": [0.8, float("nan"), 1.0]}

        metrics, sample_counts = ragas_client.summarize_scores(scores)

        assert metrics == {"faithfulness": round(0.9, 4)}
        assert sample_counts == {"faithfulness": 2}

    def test_all_nan_returns_none_mean_and_zero_count(self):
        scores = {"faithfulness": [float("nan"), float("nan")]}

        metrics, sample_counts = ragas_client.summarize_scores(scores)

        assert metrics == {"faithfulness": None}
        assert sample_counts == {"faithfulness": 0}

    def test_empty_scores_dict_returns_empty_dicts(self):
        metrics, sample_counts = ragas_client.summarize_scores({})

        assert metrics == {}
        assert sample_counts == {}


class TestPrintMetricSummary:
    def test_prints_one_line_per_metric_with_expected_format(self, capsys):
        metrics = {"faithfulness": 0.9, "answer_relevancy": 0.85}
        sample_counts = {"faithfulness": 3, "answer_relevancy": 2}

        ragas_client.print_metric_summary(metrics, sample_counts, total=3)

        captured = capsys.readouterr()
        assert captured.out == (
            "  faithfulness:      0.9  (3/3 samples scored)\n"
            "  answer_relevancy:  0.85  (2/3 samples scored)\n"
        )

    def test_none_mean_prints_none(self, capsys):
        metrics = {"faithfulness": None}
        sample_counts = {"faithfulness": 0}

        ragas_client.print_metric_summary(metrics, sample_counts, total=2)

        captured = capsys.readouterr()
        assert captured.out == "  faithfulness:      None  (0/2 samples scored)\n"


class TestBuildLlm:
    def test_uses_anthropic_provider_and_judge_model(self):
        with (
            patch("ragas_client.anthropic.AsyncAnthropic") as mock_anthropic,
            patch("ragas_client.llm_factory") as mock_llm_factory,
        ):
            result = ragas_client.build_llm()

        mock_anthropic.assert_called_once_with(api_key=ragas_client.ANTHROPIC_API_KEY)
        mock_llm_factory.assert_called_once_with(
            ragas_client.JUDGE_MODEL,
            provider="anthropic",
            client=mock_anthropic.return_value,
        )
        assert result is mock_llm_factory.return_value

    def test_drops_top_p_to_avoid_anthropic_400(self):
        with (
            patch("ragas_client.anthropic.AsyncAnthropic"),
            patch("ragas_client.llm_factory") as mock_llm_factory,
        ):
            mock_llm_factory.return_value.model_args = {
                "temperature": 0.01,
                "top_p": 0.1,
                "max_tokens": 1024,
            }

            result = ragas_client.build_llm()

        assert "top_p" not in result.model_args
        assert mock_llm_factory.return_value.model_args == {
            "temperature": 0.01,
            "max_tokens": 1024,
        }


class TestBuildEmbeddings:
    def test_points_openai_client_at_ollama(self):
        with (
            patch("ragas_client.openai.AsyncOpenAI") as mock_openai,
            patch("ragas_client.embedding_factory") as mock_embedding_factory,
        ):
            result = ragas_client.build_embeddings()

        mock_openai.assert_called_once_with(
            base_url=f"{ragas_client.OLLAMA_URL}/v1", api_key="ollama"
        )
        mock_embedding_factory.assert_called_once_with(
            "openai",
            model=ragas_client.EMBEDDING_MODEL,
            client=mock_openai.return_value,
        )
        assert result is mock_embedding_factory.return_value


class TestScoreOrNan:
    def test_returns_score_value_on_success(self, mock_metric):
        metric = mock_metric(0.75)

        result = asyncio.run(ragas_client.score_or_nan(metric, user_input="q"))

        assert result == 0.75
        metric.ascore.assert_awaited_once_with(user_input="q")

    def test_returns_nan_and_logs_on_exception(self, capsys):
        metric = type("Faithfulness", (), {})()
        metric.ascore = AsyncMock(side_effect=ValueError("boom"))

        result = asyncio.run(ragas_client.score_or_nan(metric, user_input="q"))

        assert math.isnan(result)
        captured = capsys.readouterr()
        assert "ValueError" in captured.err
        assert "boom" in captured.err
        assert "Faithfulness" in captured.err
