"""
Clean interface for LLM-based employer pair verification.

Defines abstract base class for verifiers and concrete implementations.
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

try:
    from ollama import AsyncClient
except ImportError:
    AsyncClient = None
    logging.warning("ollama library not installed. Install with: pip install ollama")

from .clustering_evaluator import EmployerPair, EvaluationOutcome

logger = logging.getLogger(__name__)

# Default model: Use faster llama3.2:1b for better throughput
# Falls back to llama3.2:3b if 1b not available
DEFAULT_MODEL = "llama3.2:1b"
FALLBACK_MODEL = "llama3.2:3b"


@dataclass
class VerifierConfig:
    """Configuration for LLM verifier."""

    model: str = "llama3.2:1b"
    prompt_template_path: Path | None = None
    prompt_template: str | None = None
    timeout: float = 30.0
    max_concurrent: int = 4
    ollama_host: str = "http://localhost:11434"
    fallback_model: str | None = FALLBACK_MODEL
    auto_pull_model: bool = True


class LLMVerifier(ABC):
    """
    Abstract base class for LLM-based employer pair verification.

    Provides clean interface for verifying if two employers are the same company.
    """

    def __init__(self, config: VerifierConfig):
        """
        Initialize verifier with configuration.

        Args:
            config: VerifierConfig with model, prompt, and other settings
        """
        self.config = config

    @abstractmethod
    async def verify_async(self, pair: EmployerPair) -> EvaluationOutcome:
        """
        Verify if two employers are the same company (async).

        Args:
            pair: EmployerPair to verify

        Returns:
            EvaluationOutcome with validation result
        """
        pass

    def verify(self, pair: EmployerPair) -> EvaluationOutcome:
        """
        Verify if two employers are the same company (synchronous wrapper).

        Args:
            pair: EmployerPair to verify

        Returns:
            EvaluationOutcome with validation result
        """
        return asyncio.run(self.verify_async(pair))

    @abstractmethod
    async def verify_batch_async(
        self, pairs: list[EmployerPair]
    ) -> list[EvaluationOutcome]:
        """
        Verify multiple pairs in parallel (async).

        Args:
            pairs: List of EmployerPair objects to verify

        Returns:
            List of EvaluationOutcome results in same order as input pairs
        """
        pass

    def verify_batch(self, pairs: list[EmployerPair]) -> list[EvaluationOutcome]:
        """
        Verify multiple pairs in parallel (synchronous wrapper).

        Args:
            pairs: List of EmployerPair objects to verify

        Returns:
            List of EvaluationOutcome results in same order as input pairs
        """
        return asyncio.run(self.verify_batch_async(pairs))

    def _load_prompt_template(self) -> str:
        """Load prompt template from file or use provided template."""
        if self.config.prompt_template:
            return self.config.prompt_template

        if self.config.prompt_template_path:
            try:
                with open(self.config.prompt_template_path) as f:
                    return f.read().strip()
            except FileNotFoundError:
                logger.error(
                    f"Prompt template not found: {self.config.prompt_template_path}"
                )
                raise

        # Try to load from Bazel runfiles
        from lib.utils.bazel_runfiles import get_template_file

        template_path = get_template_file("llm_prompt_template.txt")
        if template_path:
            try:
                with open(template_path) as f:
                    return f.read().strip()
            except FileNotFoundError:
                pass

        raise ValueError(
            "No prompt template available. Set prompt_template or prompt_template_path in config."
        )

    def _format_prompt(self, pair: EmployerPair, template: str) -> str:
        """Format prompt template with pair data."""
        # Build format dict - only include similarity if template uses it
        format_dict = {
            "emp1_name": pair.emp1_name,
            "emp1_city": pair.emp1_city or "N/A",
            "emp1_state": pair.emp1_state or "N/A",
            "emp2_name": pair.emp2_name,
            "emp2_city": pair.emp2_city or "N/A",
            "emp2_state": pair.emp2_state or "N/A",
        }

        # Only include similarity if template actually uses it (avoids KeyError)
        if "{similarity" in template:
            format_dict["similarity"] = pair.similarity

        return template.format(**format_dict)

    def _parse_response(self, response: str) -> EvaluationOutcome:
        """Parse LLM response into EvaluationOutcome."""
        if not response:
            return EvaluationOutcome.failed()

        response_upper = response.upper()
        is_same = response_upper.startswith("YES")

        if is_same:
            return EvaluationOutcome.same(response)
        else:
            return EvaluationOutcome.different(response)


class OllamaVerifier(LLMVerifier):
    """
    Ollama-based LLM verifier using HTTP API.

    Uses async HTTP API for efficient parallel processing with connection pooling.
    Includes model auto-pulling and fallback model support.
    """

    def __init__(self, config: VerifierConfig):
        super().__init__(config)
        self._client = None
        self._template = None
        # Cache of models that have been checked/verified as available
        # Prevents repeated availability checks for every LLM call
        self._checked_models: set[str] = set()

    def _get_client(self):
        """Get or create async Ollama client."""
        if self._client is None:
            if AsyncClient is None:
                logger.error(
                    "ollama library not installed. Install with: pip install ollama"
                )
                return None

            try:
                self._client = AsyncClient(host=self.config.ollama_host)
                logger.debug(
                    f"Created Ollama async client (host={self.config.ollama_host})"
                )
            except Exception as e:
                logger.error(f"Failed to create Ollama client: {e}")
                return None

        return self._client

    async def _ensure_model_available(self, model: str) -> bool:
        """
        Ensure an Ollama model is available, pulling it if necessary.

        Uses instance-level cache to avoid repeated checks for the same model.
        This prevents expensive /api/tags calls on every LLM request.

        Args:
            model: Model name to check/pull

        Returns:
            True if model is available, False otherwise
        """
        # Skip check if model was already verified (cached)
        if model in self._checked_models:
            return True

        if not self.config.auto_pull_model:
            # If auto_pull is disabled, assume model is available (benchmark script handles pulling)
            self._checked_models.add(model)
            return True

        client = self._get_client()
        if not client:
            return False

        try:
            # Check if model exists by listing models
            models_list = await client.list()
            # Handle different response formats
            # ollama.list() returns a dict with 'models' key containing list of model dicts
            if isinstance(models_list, dict):
                models = models_list.get("models", [])
            else:
                models = models_list if isinstance(models_list, list) else []

            # Extract model names from dict format
            available_models = set()
            for m in models:
                if isinstance(m, dict):
                    # Model dict has 'name' key (e.g., {"name": "llama3.2:1b", ...})
                    name = m.get("name", "")
                elif hasattr(m, "name"):
                    # Handle object format
                    name = getattr(m, "name", "")
                else:
                    name = ""
                if name:
                    available_models.add(name)

            if model in available_models:
                logger.debug(f"Model {model} is already available")
                # Cache the result to avoid future checks
                self._checked_models.add(model)
                return True

            # Model not found, pull it
            logger.info(f"Model {model} not found. Pulling from Ollama...")
            # client.pull() with stream=True may return coroutine or async iterator
            # Handle both cases
            pull_result = client.pull(model, stream=True)

            # Check if it's a coroutine (needs await) or async iterator (can iterate directly)
            if asyncio.iscoroutine(pull_result):
                # If coroutine, await it first to get the iterator
                pull_iterator = await pull_result
                async for progress in pull_iterator:
                    if isinstance(progress, dict) and "status" in progress:
                        logger.debug(f"Pulling {model}: {progress['status']}")
            else:
                # Direct async iterator
                async for progress in pull_result:
                    if isinstance(progress, dict) and "status" in progress:
                        logger.debug(f"Pulling {model}: {progress['status']}")

            logger.info(f"Successfully pulled model {model}")
            # Cache the result after successful pull
            self._checked_models.add(model)
            return True

        except Exception as e:
            logger.error(
                f"Failed to ensure model {model} is available: {e}", exc_info=True
            )
            return False

    async def verify_async(self, pair: EmployerPair) -> EvaluationOutcome:
        """Verify single pair using Ollama."""
        if self._template is None:
            self._template = self._load_prompt_template()

        prompt = self._format_prompt(pair, self._template)
        response = await self._call_ollama(prompt, model=self.config.model)

        if not response:
            return EvaluationOutcome.failed()

        return self._parse_response(response)

    async def verify_batch_async(
        self, pairs: list[EmployerPair]
    ) -> list[EvaluationOutcome]:
        """Verify multiple pairs in parallel."""
        import time

        batch_start = time.perf_counter()

        if not pairs:
            return []

        template_start = time.perf_counter()
        if self._template is None:
            self._template = self._load_prompt_template()
        template_elapsed = time.perf_counter() - template_start

        # Prepare prompts
        prompt_start = time.perf_counter()
        prompts = [self._format_prompt(pair, self._template) for pair in pairs]
        prompt_elapsed = time.perf_counter() - prompt_start

        # Process in parallel with concurrency limit
        semaphore = asyncio.Semaphore(self.config.max_concurrent)
        call_times = []

        async def verify_single(prompt: str) -> EvaluationOutcome:
            call_start = time.perf_counter()
            async with semaphore:
                try:
                    response = await self._call_ollama(prompt)
                    call_elapsed = time.perf_counter() - call_start
                    call_times.append(call_elapsed)
                    if not response:
                        return EvaluationOutcome.failed()
                    return self._parse_response(response)
                except Exception as e:
                    call_elapsed = time.perf_counter() - call_start
                    call_times.append(call_elapsed)
                    logger.error(f"Error verifying pair: {e}", exc_info=True)
                    return EvaluationOutcome.failed()

        # Create tasks for all prompts
        llm_start = time.perf_counter()
        tasks = [verify_single(prompt) for prompt in prompts]

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        llm_elapsed = time.perf_counter() - llm_start

        # Handle exceptions
        parse_start = time.perf_counter()
        outcomes = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Exception verifying pair {i}: {result}")
                outcomes.append(EvaluationOutcome.failed())
            else:
                outcomes.append(result)
        parse_elapsed = time.perf_counter() - parse_start

        total_elapsed = time.perf_counter() - batch_start

        # Log timing breakdown
        if call_times:
            avg_call_time = sum(call_times) / len(call_times)
            min_call_time = min(call_times)
            max_call_time = max(call_times)
            logger.info(
                f"Batch verification timing: total={total_elapsed:.3f}s, "
                f"template={template_elapsed:.3f}s, prompt={prompt_elapsed:.3f}s, "
                f"llm={llm_elapsed:.3f}s (avg={avg_call_time:.3f}s, min={min_call_time:.3f}s, max={max_call_time:.3f}s), "
                f"parse={parse_elapsed:.3f}s, pairs={len(pairs)}, throughput={len(pairs) / total_elapsed:.1f} pairs/s"
            )

        return outcomes

    async def _call_ollama(self, prompt: str, model: str | None = None) -> str | None:
        """Call Ollama API with prompt."""
        import time

        call_start = time.perf_counter()
        timing = {}

        if model is None:
            model = self.config.model

        # Ensure model is available (auto-pull if needed)
        # Note: This check is cached per verifier instance to avoid repeated /api/tags calls
        ensure_start = time.perf_counter()
        await self._ensure_model_available(model)
        ensure_elapsed = time.perf_counter() - ensure_start
        timing["ensure_model"] = ensure_elapsed
        if ensure_elapsed > 0.1:
            logger.debug(
                f"Model availability check took {ensure_elapsed:.3f}s (uncached)"
            )

        client_start = time.perf_counter()
        client = self._get_client()
        timing["get_client"] = time.perf_counter() - client_start
        if not client:
            return None

        try:
            request_start = time.perf_counter()
            response = await asyncio.wait_for(
                client.chat(
                    model=model, messages=[{"role": "user", "content": prompt}]
                ),
                timeout=self.config.timeout,
            )
            request_elapsed = time.perf_counter() - request_start
            timing["llm_request"] = request_elapsed

            parse_start = time.perf_counter()
            if response and "message" in response and "content" in response["message"]:
                content = response["message"]["content"].strip()
                timing["parse_response"] = time.perf_counter() - parse_start

                total_elapsed = time.perf_counter() - call_start
                timing["total"] = total_elapsed

                # Log detailed timing for slow calls or when debugging
                if total_elapsed > 1.0:
                    logger.debug(
                        f"LLM call timing: total={total_elapsed:.3f}s, "
                        f"ensure={timing.get('ensure_model', 0):.3f}s, "
                        f"client={timing.get('get_client', 0):.3f}s, "
                        f"request={timing.get('llm_request', 0):.3f}s, "
                        f"parse={timing.get('parse_response', 0):.3f}s"
                    )
                return content

            timing["parse_response"] = time.perf_counter() - parse_start
            logger.warning(f"Unexpected response format from Ollama: {response}")
            return None

        except TimeoutError:
            elapsed = time.perf_counter() - call_start
            logger.warning(
                f"Ollama call timed out after {elapsed:.2f}s (model: {model})"
            )
            # Try fallback model if primary timed out
            if model == self.config.model and self.config.fallback_model:
                logger.info(f"Trying fallback model: {self.config.fallback_model}")
                return await self._call_ollama(prompt, model=self.config.fallback_model)
            return None
        except Exception as e:
            elapsed = time.perf_counter() - call_start
            error_str = str(e)
            # Check if model not found error
            if (
                "404" in error_str
                or "not found" in error_str.lower()
                or "try pulling" in error_str.lower()
            ):
                # Try fallback model
                if model == self.config.model and self.config.fallback_model:
                    logger.info(
                        f"Model {model} not found. Trying fallback: {self.config.fallback_model}"
                    )
                    await self._ensure_model_available(self.config.fallback_model)
                    return await self._call_ollama(
                        prompt, model=self.config.fallback_model
                    )
            logger.error(
                f"Error calling Ollama (took {elapsed:.3f}s): {e}", exc_info=True
            )
            return None


def create_verifier(
    model: str = DEFAULT_MODEL,
    prompt_template_path: Path | None = None,
    prompt_template: str | None = None,
    timeout: float = 30.0,
    max_concurrent: int = 4,
    ollama_host: str | None = None,
    fallback_model: str | None = FALLBACK_MODEL,
    auto_pull_model: bool = True,
) -> LLMVerifier:
    """
    Factory function to create verifier with specified configuration.

    Args:
        model: Model name (default: llama3.2:1b)
        prompt_template_path: Path to prompt template file
        prompt_template: Prompt template as string (alternative to file)
        timeout: Request timeout in seconds
        max_concurrent: Maximum concurrent requests for batch verification
        ollama_host: Ollama server host (default: from OLLAMA_HOST env or http://localhost:11434)
        fallback_model: Fallback model to use if primary fails (default: llama3.2:3b)
        auto_pull_model: Whether to automatically pull models if missing (default: True)

    Returns:
        LLMVerifier instance
    """
    if ollama_host is None:
        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    config = VerifierConfig(
        model=model,
        prompt_template_path=prompt_template_path,
        prompt_template=prompt_template,
        timeout=timeout,
        max_concurrent=max_concurrent,
        ollama_host=ollama_host,
        fallback_model=fallback_model,
        auto_pull_model=auto_pull_model,
    )

    return OllamaVerifier(config)


# Backward compatibility functions - use new verifier internally
def call_ollama(
    prompt: str, model: str = DEFAULT_MODEL, timeout: float = 30.0
) -> str | None:
    """
    Call Ollama LLM via HTTP API (synchronous wrapper).

    Backward compatibility function. Uses OllamaVerifier internally.

    Args:
        prompt: The prompt text to send to the LLM
        model: Ollama model name (default: llama3.2:1b for speed)
        timeout: Request timeout in seconds (default: 30s)

    Returns:
        LLM response text, or None if call failed
    """
    return asyncio.run(call_ollama_async(prompt, model, timeout))


async def call_ollama_async(
    prompt: str, model: str = DEFAULT_MODEL, timeout: float = 30.0
) -> str | None:
    """
    Call Ollama LLM via HTTP API (async, connection pooling).

    Backward compatibility function. Uses OllamaVerifier internally.

    Args:
        prompt: The prompt text to send to the LLM
        model: Ollama model name (default: llama3.2:1b for speed)
        timeout: Request timeout in seconds (default: 30s)

    Returns:
        LLM response text, or None if call failed
    """
    verifier = create_verifier(model=model, timeout=timeout)
    if not isinstance(verifier, OllamaVerifier):
        return None
    return await verifier._call_ollama(prompt, model=model)


async def validate_pair_with_llm_async(
    pair: EmployerPair,
    prompt_template_path: Path | None = None,
    model: str = DEFAULT_MODEL,
) -> EvaluationOutcome:
    """
    Use LLM to validate if two employers are the same company (async).

    Backward compatibility function. Uses OllamaVerifier internally.

    Args:
        pair: EmployerPair dataclass with employer information
        prompt_template_path: Optional path to prompt template file.
        model: Model to use (default: llama3.2:1b)

    Returns:
        EvaluationOutcome with validation result
    """
    verifier = create_verifier(model=model, prompt_template_path=prompt_template_path)
    return await verifier.verify_async(pair)


def validate_pair_with_llm(
    pair: EmployerPair, prompt_template_path: Path | None = None
) -> EvaluationOutcome:
    """
    Use LLM to validate if two employers are the same company (synchronous wrapper).

    Backward compatibility function. Uses OllamaVerifier internally.

    Args:
        pair: EmployerPair dataclass with employer information
        prompt_template_path: Optional path to prompt template file.
            If not provided, uses Bazel data dependency //scripts/salary:llm_prompt_template.txt

    Returns:
        EvaluationOutcome with validation result
    """
    return asyncio.run(validate_pair_with_llm_async(pair, prompt_template_path))


async def validate_pairs_parallel_async(
    pairs: list[EmployerPair],
    prompt_template_path: Path | None = None,
    model: str = DEFAULT_MODEL,
    max_concurrent: int = 4,
    batch_size: int | None = None,
) -> list[EvaluationOutcome]:
    """
    Validate multiple pairs in parallel using async HTTP API.

    Backward compatibility function. Uses OllamaVerifier internally.

    Processes pairs concurrently for 2-4x speedup compared to sequential calls.

    Args:
        pairs: List of EmployerPair objects to validate
        prompt_template_path: Optional path to prompt template file
        model: Model to use (default: llama3.2:1b)
        max_concurrent: Maximum concurrent requests (default: 4, matches Ollama server config)
        batch_size: Optional batch size for processing (default: None = process all)

    Returns:
        List of EvaluationOutcome results in same order as input pairs
    """
    if not pairs:
        return []

    verifier = create_verifier(
        model=model,
        prompt_template_path=prompt_template_path,
        max_concurrent=max_concurrent,
    )

    # Process in batches if specified
    if batch_size:
        results = []
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            batch_results = await verifier.verify_batch_async(batch)
            results.extend(batch_results)
        return results
    else:
        return await verifier.verify_batch_async(pairs)
