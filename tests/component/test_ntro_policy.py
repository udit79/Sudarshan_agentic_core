import pytest
from pipelines.common.ntro_policy import (
    validate_classification,
    require_classification,
    require_classification_access,
    validate_distribution,
    sanitize_text,
    sanitize_output,
    contains_hindi,
    bilingual_label,
    validate_ntro_response
)


def test_validate_classification():
    assert validate_classification("secret") == "SECRET"
    assert validate_classification("TOP secret") == "TOP SECRET"
    assert validate_classification("UNCLASSIFIED") == "UNCLASSIFIED"
    # Invalid values fallback to RESTRICTED
    assert validate_classification("public") == "RESTRICTED"
    assert validate_classification("") == "RESTRICTED"


def test_require_classification_rejects_misclassified_requests():
    assert require_classification("secret") == "SECRET"
    with pytest.raises(ValueError, match="classification_level"):
        require_classification("public")


def test_classification_access_requires_equal_or_higher_clearance():
    assert require_classification_access("SECRET", "RESTRICTED") == ("SECRET", "RESTRICTED")
    with pytest.raises(PermissionError, match="cannot access"):
        require_classification_access("RESTRICTED", "SECRET")


def test_validate_distribution():
    assert validate_distribution("pmo") == "PMO"
    assert validate_distribution("cAbInEt SeCrEtArIaT") == "Cabinet Secretariat"
    # Custom distribution remains unchanged
    assert validate_distribution("Custom Dept") == "Custom Dept"
    # Empty falls back to default
    assert validate_distribution("") == "Authorized NTRO personnel"


def test_sanitize_text():
    # Strip AI references
    res1 = sanitize_text("This is an analysis. As an AI language model, I suggest...")
    assert "As an AI language model" not in res1.text
    assert res1.violations_found > 0
    
    # Strip tool artifacts
    res2 = sanitize_text("According to recall_sudarshan_memory, the data is...")
    assert "recall_sudarshan_memory" not in res2.text
    assert res2.violations_found > 0
    
    # Clean text unchanged
    res3 = sanitize_text("The operation concluded successfully.")
    assert res3.text == "The operation concluded successfully."
    assert res3.violations_found == 0


def test_sanitize_output_recursive():
    data = {
        "title": "Report",
        "details": ["As an AI, I note this", "Valid point"],
        "nested": {"key": "According to CrewAI"}
    }
    cleaned = sanitize_output(data)
    assert cleaned["title"] == "Report"
    assert "AI" not in cleaned["details"][0]
    assert "CrewAI" not in cleaned["nested"]["key"]


def test_bilingual_support():
    assert contains_hindi("This has हिंदी text") is True
    assert contains_hindi("Only English") is False
    assert bilingual_label("Secretariat", "सचिवालय") == "Secretariat / सचिवालय"


def test_validate_ntro_response():
    response = {
        "status": "succeeded",
        "output": "As an AI, here is the result.",
        "metadata": {
            "pipeline": "advisory",
            "chain_of_thought": "I should do this...",
            "openai_api_key": "sk-1234"
        }
    }
    cleaned = validate_ntro_response(response)
    # Output sanitized
    assert "As an AI" not in cleaned["output"]
    # Forbidden metadata stripped
    assert "chain_of_thought" not in cleaned["metadata"]
    assert "openai_api_key" not in cleaned["metadata"]
    # Permitted metadata kept
    assert cleaned["metadata"]["pipeline"] == "advisory"
