from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "LOCATION",
    "DATE_TIME",
    "CREDIT_CARD",
    "IBAN_CODE",
    "MEDICAL_LICENSE",
    "NRP",
    "US_SSN",
    "US_PASSPORT",
    "IP_ADDRESS",
]

_OPERATORS: dict[str, OperatorConfig] = {
    "PERSON": OperatorConfig("replace", {"new_value": "[NAME]"}),
    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[EMAIL]"}),
    "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[PHONE]"}),
    "LOCATION": OperatorConfig("replace", {"new_value": "[ADDRESS]"}),
    "DATE_TIME": OperatorConfig("replace", {"new_value": "[DATE]"}),
    "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[CARD]"}),
    "IBAN_CODE": OperatorConfig("replace", {"new_value": "[CARD]"}),
    "MEDICAL_LICENSE": OperatorConfig("replace", {"new_value": "[MEDICAL]"}),
    "NRP": OperatorConfig("replace", {"new_value": "[ID]"}),
    "US_SSN": OperatorConfig("replace", {"new_value": "[ID]"}),
    "US_PASSPORT": OperatorConfig("replace", {"new_value": "[ID]"}),
    "IP_ADDRESS": OperatorConfig("replace", {"new_value": "[IP]"}),
}

# Module-level singletons — spaCy load is expensive, do it once
_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()


def redact_pii(text: str) -> str:
    """Detect and redact PII in text, replacing it with typed placeholders."""
    if not text:
        return text

    results = _analyzer.analyze(text=text, entities=_ENTITIES, language="en")
    if not results:
        return text

    anonymized = _anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators=_OPERATORS,
    )
    return anonymized.text
