import re

from compare import build_report


class TestBuildReport:
    def _baseline_metrics(self) -> dict:
        return {"faithfulness": 0.61, "answer_relevancy": 0.72}

    def _rag_metrics(self) -> dict:
        return {
            "context_recall": 0.78,
            "context_precision": 0.82,
            "faithfulness": 0.89,
            "answer_relevancy": 0.85,
        }

    def test_report_is_a_string(self):
        report = build_report(self._baseline_metrics(), self._rag_metrics())
        assert isinstance(report, str)

    def test_report_contains_markdown_table_header(self):
        report = build_report(self._baseline_metrics(), self._rag_metrics())
        assert "| Metric" in report
        assert "No-RAG Baseline" in report
        assert "RAG Pipeline" in report
        assert "Delta" in report

    def test_all_four_metrics_appear_in_report(self):
        report = build_report(self._baseline_metrics(), self._rag_metrics())
        assert "context_recall" in report
        assert "context_precision" in report
        assert "faithfulness" in report
        assert "answer_relevancy" in report

    def test_na_displayed_for_missing_baseline_metric(self):
        report = build_report(self._baseline_metrics(), self._rag_metrics())
        assert "N/A" in report

    def test_positive_delta_prefixed_with_plus(self):
        report = build_report(self._baseline_metrics(), self._rag_metrics())
        # RAG faithfulness (0.89) > baseline faithfulness (0.61), delta = +0.28
        assert "+0.2800" in report

    def test_rag_only_metric_delta_shows_full_rag_value(self):
        """When baseline has N/A, delta equals the RAG metric value."""
        report = build_report(self._baseline_metrics(), self._rag_metrics())
        # context_recall = 0.78, baseline N/A → delta = +0.78
        assert "+0.7800" in report

    def test_negative_delta_shows_negative_sign(self):
        baseline = {"faithfulness": 0.90}
        rag = {"faithfulness": 0.70}
        report = build_report(baseline, rag)
        assert "-0.2000" in report

    def test_report_contains_date_heading(self):
        report = build_report(self._baseline_metrics(), self._rag_metrics())
        assert re.search(r"\d{4}-\d{2}-\d{2}", report)
