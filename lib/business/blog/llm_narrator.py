"""LLM prose layer for blog post generation.

Uses Ollama (local LLM) to convert structured analysis data into
expert-quality prose. Falls back to rule-based text if Ollama is unavailable.
"""

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3.2:3b"
DEFAULT_HOST = "http://localhost:11434"

SYSTEM_PROMPT = """You are an expert immigration analyst writing for a professional audience
of visa applicants and immigration attorneys. Your writing style is:
- Factual and data-driven (cite specific numbers, dates, and movements)
- Concise but thorough (every sentence adds value)
- Balanced (acknowledge uncertainty, avoid over-promising)
- Professional tone (not casual, not academic — like a Bloomberg analyst note)

Never use first person. Write in third person ("the data shows", "applicants should note").
Never use emojis or exclamation marks. Do not invent data — only reference what is provided."""


class LlmNarrator:
    """Converts structured bulletin analysis into expert-quality prose via Ollama.

    Gracefully falls back to rule-based text if Ollama is unavailable or fails.
    """

    def __init__(
        self,
        model: str | None = None,
        ollama_host: str | None = None,
    ):
        self.model = model or os.environ.get("BLOG_LLM_MODEL", DEFAULT_MODEL)
        self.ollama_host = ollama_host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            from ollama import Client
        except ImportError:
            logger.info("ollama library not installed — using rule-based fallback")
            return None

        try:
            self._client = Client(host=self.ollama_host)
            self._client.list()
            return self._client
        except Exception as e:
            logger.info(f"Ollama not reachable ({e}) — using rule-based fallback")
            self._client = None
            return None

    def generate_outlook_prose(self, structured_context: dict) -> str | None:
        """Generate the Future Outlook section as expert prose.

        Args:
            structured_context: Dict with keys:
                - summary: overall tone string
                - series_outlooks: list of per-series dicts
                - regime_descriptions: list of regime signal dicts

        Returns:
            Expert prose string, or None if LLM unavailable (caller uses fallback).
        """
        client = self._get_client()
        if not client:
            return None

        prompt = self._build_outlook_prompt(structured_context)
        return self._call_llm(prompt)

    def generate_summary_lede(self, bulletin_month: str, movements: dict) -> str | None:
        """Generate a 2-sentence expert framing at the top of the post.

        Args:
            bulletin_month: e.g. "March 2026"
            movements: dict with "employment" and "family" lists of movement strings

        Returns:
            Expert lede string, or None if LLM unavailable.
        """
        client = self._get_client()
        if not client:
            return None

        emp_count = len(movements.get("employment", []))
        fam_count = len(movements.get("family", []))

        prompt = (
            f"Write a 2-sentence opening summary for a Visa Bulletin analysis for {bulletin_month}. "
            f"There were {emp_count} significant employment-based movements and "
            f"{fam_count} family-sponsored movements this month. "
            "Be concise and professional. Do not use first person."
        )
        return self._call_llm(prompt)

    def generate_series_narrative(
        self, label: str, movement_days: int, regime: str | None,
        avg_pace: float | None, seasonal_deviation: float | None,
    ) -> str | None:
        """Generate 2-3 sentence explanation of why a specific series moved.

        Returns None if LLM unavailable (caller uses structured fallback).
        """
        client = self._get_client()
        if not client:
            return None

        parts = [f"Write 2-3 sentences explaining the {label} visa bulletin movement."]
        if movement_days > 0:
            parts.append(f"The cutoff date advanced by {movement_days} days.")
        elif movement_days < 0:
            parts.append(f"The cutoff date retrogressed by {abs(movement_days)} days.")
        else:
            parts.append("The cutoff date did not move.")

        if regime:
            parts.append(f"The series is currently in a {regime} regime.")
        if avg_pace is not None:
            parts.append(f"The 12-month average pace is {avg_pace:.1f} days/month.")
        if seasonal_deviation is not None:
            if seasonal_deviation > 20:
                parts.append(f"Recent months are running {seasonal_deviation:.1f} days/month faster than seasonal norms.")
            elif seasonal_deviation < -20:
                parts.append(f"Recent months are running {abs(seasonal_deviation):.1f} days/month slower than seasonal norms.")
            else:
                parts.append("Recent pace is in line with seasonal norms.")

        parts.append("Explain what this means for applicants. Be specific and data-driven.")
        return self._call_llm(" ".join(parts))

    def _build_outlook_prompt(self, ctx: dict) -> str:
        lines = [
            "Write a 3-4 paragraph Future Outlook section for a visa bulletin analysis blog post.",
            "",
            f"Overall summary: {ctx.get('summary', 'Mixed signals across categories.')}",
            "",
            "Per-series data:",
        ]

        for s in ctx.get("series_outlooks", []):
            parts = [f"- {s['label']}:"]
            if s.get("predicted_date"):
                parts.append(f"predicted cutoff {s['predicted_date']}")
            if s.get("regime_label"):
                parts.append(f"regime={s['regime_label']}")
            if s.get("avg_pace") is not None:
                parts.append(f"12m avg pace={s['avg_pace']}d/mo")
            if s.get("seasonal_deviation") is not None:
                parts.append(f"seasonal deviation={s['seasonal_deviation']}d/mo")
            if s.get("pace_trend"):
                parts.append(f"trend={s['pace_trend']}")
            if s.get("confidence_note"):
                parts.append(f"confidence={s['confidence_note']}")
            lines.append(", ".join(parts))

        lines.extend([
            "",
            "Regime context:",
        ])
        for rd in ctx.get("regime_descriptions", []):
            lines.append(f"- {rd['description']}")

        lines.extend([
            "",
            "Instructions:",
            "- Reference specific series by name (e.g., 'EB-2 India')",
            "- Mention pace numbers and regime states where relevant",
            "- Note any acceleration or deceleration trends",
            "- Acknowledge uncertainty where confidence is low",
            "- End with a practical note for applicants",
            "- Do not use first person or emojis",
        ])

        return "\n".join(lines)

    def _call_llm(self, prompt: str) -> str | None:
        """Call Ollama and return the response text, or None on failure."""
        client = self._get_client()
        if not client:
            return None

        try:
            response = client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.3, "num_predict": 512},
            )
            content = response.get("message", {}).get("content", "")
            if content and len(content.strip()) > 20:
                return content.strip()
            logger.warning("LLM returned empty or too-short response")
            return None
        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return None
