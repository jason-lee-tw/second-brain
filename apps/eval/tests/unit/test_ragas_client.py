from unittest.mock import patch

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
