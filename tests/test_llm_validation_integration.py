"""
Integration tests for LLM validation with real Ollama calls.

These tests REQUIRE Ollama to be installed and available. Tests will FAIL if Ollama is not found.
Mark with @pytest.mark.integration to run separately from unit tests.
"""

import subprocess
from pathlib import Path

import pytest

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from lib.business.salary.clustering_evaluator import EmployerPair, EvaluationOutcome
from lib.business.salary.llm_verifier import call_ollama, validate_pair_with_llm


def check_ollama_available():
    """
    Check if hermetic Ollama is available via Bazel.
    
    Raises AssertionError with clear message if Ollama is not available.
    This ensures tests FAIL (not skip) if dependency is missing.
    """
    import os

    # Try to find hermetic Ollama binary (from @ollama//:ollama data dependency)
    runfiles_base = os.environ.get('TEST_SRCDIR') or os.environ.get('BUILD_WORKSPACE_DIRECTORY')
    ollama_binary = None

    if runfiles_base:
        possible_paths = [
            Path(runfiles_base) / '_main' / 'external' / '+ollama_hermetic_extension+ollama' / 'ollama',
            Path(runfiles_base) / 'external' / '+ollama_hermetic_extension+ollama' / 'ollama',
        ]
        for path in possible_paths:
            if path.exists() and os.access(path, os.X_OK):
                ollama_binary = str(path)
                break

    # Fallback to system ollama if hermetic not found
    if not ollama_binary:
        result = subprocess.run(["which", "ollama"], capture_output=True, timeout=5)
        if result.returncode == 0:
            ollama_binary = result.stdout.decode().strip()

    if not ollama_binary:
        raise AssertionError(
            "Ollama binary not found. "
            "Hermetic Ollama should be provided via @ollama//:ollama data dependency. "
            "If running outside Bazel, install with: brew install ollama (macOS) or visit https://ollama.ai/"
        )

    try:
        # Check if Ollama works (try listing models)
        list_result = subprocess.run(
            [ollama_binary, "list"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if list_result.returncode != 0:
            raise AssertionError(
                f"Ollama binary found at {ollama_binary} but not working. "
                "Check that Ollama service is running: ollama serve"
            )

        # Check if llama3.2:3b model is available
        if "llama3.2:3b" not in list_result.stdout and "mistral" not in list_result.stdout:
            raise AssertionError(
                "Ollama is available but no suitable model found. "
                "Install a model with: bazel run @ollama//:pull_model (hermetic) or ollama pull llama3.2:3b (system)"
            )
    except subprocess.TimeoutExpired:
        raise AssertionError("Ollama check timed out. Is Ollama service running?")
    except FileNotFoundError:
        raise AssertionError(
            f"Ollama binary not executable at {ollama_binary}. "
            "Check permissions or reinstall Ollama."
        )


@pytest.mark.integration
class TestLLMValidationIntegration:
    """Integration tests that make real Ollama LLM calls."""

    def setup_method(self):
        """Check Ollama availability before each test - FAIL if not available."""
        check_ollama_available()

    def test_call_ollama_basic(self):
        """Test that call_ollama can make a basic call to Ollama."""
        response = call_ollama("Say YES if this is a test, otherwise say NO.")

        assert response is not None
        assert isinstance(response, str)
        assert len(response) > 0

        # Should respond with YES or NO
        response_upper = response.upper()
        assert "YES" in response_upper or "NO" in response_upper

    def test_validate_pair_same_company(self):
        """Test LLM validation for clearly same company."""
        pair = EmployerPair(
            emp1_name="Google Inc.",
            emp1_city="Mountain View",
            emp1_state="CA",
            emp2_name="Google LLC",
            emp2_city="Mountain View",
            emp2_state="CA",
            similarity=0.95
        )

        # Template is provided via Bazel data dependency (//scripts/salary:llm_prompt_template.txt)
        # No need to specify path - it's found via runfiles
        outcome = validate_pair_with_llm(pair)

        assert outcome is not None
        assert isinstance(outcome, EvaluationOutcome)
        # Should recognize these as same company
        assert outcome.is_same is True
        assert outcome.response is not None
        assert len(outcome.response) > 0

    def test_validate_pair_different_companies(self):
        """Test LLM validation for clearly different companies."""
        pair = EmployerPair(
            emp1_name="Google Inc.",
            emp1_city="Mountain View",
            emp1_state="CA",
            emp2_name="Microsoft Corporation",
            emp2_city="Redmond",
            emp2_state="WA",
            similarity=0.30
        )

        # Template is provided via Bazel data dependency, no need to specify path
        outcome = validate_pair_with_llm(pair)

        assert outcome is not None
        assert isinstance(outcome, EvaluationOutcome)
        # Should recognize these as different companies
        assert outcome.is_same is False
        assert outcome.response is not None
        assert len(outcome.response) > 0

    def test_validate_pair_ambiguous_case(self):
        """Test LLM validation for ambiguous case (may vary by model)."""
        pair = EmployerPair(
            emp1_name="JPMorgan Chase",
            emp1_city="New York",
            emp1_state="NY",
            emp2_name="JP Morgan",
            emp2_city="New York",
            emp2_state="NY",
            similarity=0.85
        )

        # Template is provided via Bazel data dependency, no need to specify path
        outcome = validate_pair_with_llm(pair)

        assert outcome is not None
        assert isinstance(outcome, EvaluationOutcome)
        # Should return a decision (True or False), not None
        assert outcome.is_same is not None
        assert outcome.response is not None
        assert len(outcome.response) > 0
