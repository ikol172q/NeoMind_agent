"""
Structured Research Workflow for NeoMind Agent.

Provides a multi-phase research pipeline that systematically
investigates questions using search, synthesis, and validation.

Created: 2026-04-02 (Phase 1 - Chat 搜索增强)
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import List, Dict, Optional, Any, Callable, Awaitable, Tuple
from dataclasses import dataclass, field
from enum import Enum


class ResearchPhase(Enum):
    """Phases of the structured research pipeline."""
    QUESTION_CLARIFICATION = "question_clarification"
    SOURCE_DISCOVERY = "source_discovery"
    INFORMATION_EXTRACTION = "information_extraction"
    CROSS_VALIDATION = "cross_validation"
    SYNTHESIS = "synthesis"
    CONCLUSION = "conclusion"


@dataclass
class PhaseResult:
    """Result of a single research phase."""
    phase: ResearchPhase
    status: str  # "completed", "skipped", "failed"
    data: Any
    duration_ms: float
    notes: str = ""


@dataclass
class ResearchResult:
    """Final result of a complete research workflow execution."""
    question: str
    clarified_question: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    facts: List[Dict[str, Any]] = field(default_factory=list)
    validated_facts: List[Dict[str, Any]] = field(default_factory=list)
    synthesis: str = ""
    conclusion: str = ""
    phase_results: Dict[str, PhaseResult] = field(default_factory=dict)
    total_duration_ms: float = 0.0
    confidence: float = 0.0  # 0-1


class ResearchWorkflow:
    """
    6-phase structured research pipeline.

    Phases:
    1. Question Clarification - extract key terms and sub-questions
    2. Source Discovery - search for relevant sources
    3. Information Extraction - pull facts from discovered sources
    4. Cross Validation - check fact consistency across sources
    5. Synthesis - combine validated facts into coherent narrative
    6. Conclusion - produce final answer with confidence score

    Usage:
        workflow = ResearchWorkflow(search_fn=my_search, llm_fn=my_llm)
        result = await workflow.execute("What causes aurora borealis?")
    """

    PHASES = [phase for phase in ResearchPhase]

    def __init__(
        self,
        search_fn: Optional[Callable[..., Awaitable[List[Any]]]] = None,
        llm_fn: Optional[Callable[..., Awaitable[str]]] = None,
    ) -> None:
        """
        Initialize the research workflow.

        Args:
            search_fn: Async callable(query) -> List[SearchResult]
            llm_fn: Async callable(prompt) -> str (for synthesis/analysis)
        """
        self.search_fn = search_fn
        self.llm_fn = llm_fn
        self.current_phase: Optional[ResearchPhase] = None
        self.phase_results: Dict[str, PhaseResult] = {}

    async def execute(
        self,
        question: str,
        max_sources: int = 10,
    ) -> ResearchResult:
        """
        Execute the full 6-phase research pipeline.

        Args:
            question: The research question to investigate.
            max_sources: Maximum number of sources to discover.

        Returns:
            ResearchResult with all findings and metadata.
        """
        start_time = time.time()

        # Phase 1: Question Clarification
        clarified_question = await self._run_phase(
            ResearchPhase.QUESTION_CLARIFICATION,
            self._clarify_question,
            question,
        )
        if clarified_question is None:
            clarified_question = question

        # Phase 2: Source Discovery
        sources = await self._run_phase(
            ResearchPhase.SOURCE_DISCOVERY,
            self._discover_sources,
            clarified_question,
            max_sources,
        )
        if sources is None:
            sources = []

        # Phase 3: Information Extraction
        facts = await self._run_phase(
            ResearchPhase.INFORMATION_EXTRACTION,
            self._extract_information,
            sources,
        )
        if facts is None:
            facts = []

        # Phase 4: Cross Validation
        validated_facts = await self._run_phase(
            ResearchPhase.CROSS_VALIDATION,
            self._cross_validate,
            facts,
        )
        if validated_facts is None:
            validated_facts = facts

        # Phase 5: Synthesis
        synthesis = await self._run_phase(
            ResearchPhase.SYNTHESIS,
            self._synthesize,
            validated_facts,
            clarified_question,
        )
        if synthesis is None:
            synthesis = ""

        # Phase 6: Conclusion
        conclusion_result = await self._run_phase(
            ResearchPhase.CONCLUSION,
            self._conclude,
            synthesis,
            clarified_question,
        )
        if conclusion_result is None:
            conclusion_text = ""
            confidence = 0.0
        else:
            conclusion_text, confidence = conclusion_result

        total_duration_ms = (time.time() - start_time) * 1000

        return ResearchResult(
            question=question,
            clarified_question=clarified_question,
            sources=sources,
            facts=facts,
            validated_facts=validated_facts,
            synthesis=synthesis,
            conclusion=conclusion_text,
            phase_results=dict(self.phase_results),
            total_duration_ms=total_duration_ms,
            confidence=confidence,
        )

    async def _run_phase(
        self,
        phase: ResearchPhase,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
    ) -> Any:
        """
        Run a single phase with timing and error handling.

        Args:
            phase: The research phase to execute.
            fn: Async function implementing the phase logic.
            *args: Arguments forwarded to fn.

        Returns:
            The phase output, or None if the phase failed.
        """
        self.current_phase = phase
        phase_start = time.time()

        try:
            result = await fn(*args)
            duration_ms = (time.time() - phase_start) * 1000
            self.phase_results[phase.value] = PhaseResult(
                phase=phase,
                status="completed",
                data=result,
                duration_ms=duration_ms,
            )
            return result
        except Exception as exc:
            duration_ms = (time.time() - phase_start) * 1000
            self.phase_results[phase.value] = PhaseResult(
                phase=phase,
                status="failed",
                data=None,
                duration_ms=duration_ms,
                notes=f"Error: {exc}",
            )
            return None

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _clarify_question(self, question: str) -> str:
        """
        Phase 1: Clarify and decompose the research question.

        Extracts key terms and generates sub-questions. If an LLM function
        is available it will be used for richer clarification; otherwise a
        heuristic approach is applied.

        Args:
            question: The original research question.

        Returns:
            A clarified/expanded version of the question.
        """
        if self.llm_fn is not None:
            prompt = (
                "You are a research assistant. Clarify the following question "
                "by identifying key terms, implicit assumptions, and up to 3 "
                "sub-questions that would help answer it. Return ONLY the "
                "clarified question in a single paragraph.\n\n"
                f"Question: {question}"
            )
            return await self.llm_fn(prompt)

        # Heuristic fallback: extract key terms and build a clearer query
        stop_words = {
            "a", "an", "the", "is", "are", "was", "were", "what", "how",
            "why", "when", "where", "who", "which", "do", "does", "did",
            "can", "could", "would", "should", "in", "on", "at", "to",
            "for", "of", "with", "and", "or", "but", "not", "it", "its",
        }
        words = re.findall(r"[a-zA-Z0-9]+", question.lower())
        key_terms = [w for w in words if w not in stop_words and len(w) > 2]

        if key_terms:
            return f"{question} [key terms: {', '.join(key_terms)}]"
        return question

    async def _discover_sources(
        self,
        question: str,
        max_sources: int,
    ) -> List[Dict[str, Any]]:
        """
        Phase 2: Discover relevant sources via search.

        Args:
            question: The clarified research question.
            max_sources: Maximum number of sources to return.

        Returns:
            List of source dicts with at minimum 'title', 'url', 'snippet'.
        """
        if self.search_fn is None:
            return []

        raw_results = await self.search_fn(question)
        sources: List[Dict[str, Any]] = []

        for result in raw_results[:max_sources]:
            if isinstance(result, dict):
                sources.append(result)
            else:
                # Assume SearchResult-like dataclass with attributes
                sources.append({
                    "title": getattr(result, "title", ""),
                    "url": getattr(result, "url", ""),
                    "snippet": getattr(result, "snippet", ""),
                    "source": getattr(result, "source", "unknown"),
                    "content": getattr(result, "content", None),
                    "relevance_score": getattr(result, "relevance_score", 0.0),
                })

        return sources

    async def _extract_information(
        self,
        sources: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Phase 3: Extract discrete facts from discovered sources.

        Each fact includes the claim text, the source it came from,
        and an initial confidence score.

        Args:
            sources: Source dicts from the discovery phase.

        Returns:
            List of fact dicts with 'claim', 'source_url', 'confidence'.
        """
        if not sources:
            return []

        facts: List[Dict[str, Any]] = []

        if self.llm_fn is not None:
            for source in sources:
                text = source.get("content") or source.get("snippet", "")
                if not text:
                    continue

                prompt = (
                    "Extract the key factual claims from the following text. "
                    "Return each claim on its own line, prefixed with '- '.\n\n"
                    f"Text: {text}"
                )
                response = await self.llm_fn(prompt)

                for line in response.splitlines():
                    line = line.strip()
                    if line.startswith("- "):
                        claim = line[2:].strip()
                        if claim:
                            facts.append({
                                "claim": claim,
                                "source_url": source.get("url", ""),
                                "source_title": source.get("title", ""),
                                "confidence": source.get("relevance_score", 0.5),
                            })
        else:
            # Heuristic: treat each source snippet as a single fact
            for source in sources:
                snippet = source.get("snippet", "")
                if snippet:
                    facts.append({
                        "claim": snippet,
                        "source_url": source.get("url", ""),
                        "source_title": source.get("title", ""),
                        "confidence": source.get("relevance_score", 0.5),
                    })

        return facts

    async def _cross_validate(
        self,
        facts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Phase 4: Cross-validate facts for consistency across sources.

        Facts that appear in multiple sources get a confidence boost.
        Contradictory facts are flagged.

        Args:
            facts: Extracted fact dicts from phase 3.

        Returns:
            Validated fact dicts with updated confidence and validation metadata.
        """
        if not facts:
            return []

        if self.llm_fn is not None:
            # Build a numbered list of claims for the LLM
            claims_text = "\n".join(
                f"{i + 1}. {f['claim']}" for i, f in enumerate(facts)
            )
            prompt = (
                "Review the following numbered claims for consistency. "
                "For each claim number, respond with SUPPORTED, CONTRADICTED, "
                "or UNVERIFIED on its own line (e.g. '1: SUPPORTED').\n\n"
                f"{claims_text}"
            )
            response = await self.llm_fn(prompt)

            validation_map: Dict[int, str] = {}
            for line in response.splitlines():
                line = line.strip()
                match = re.match(r"(\d+)\s*[:.\-]\s*(SUPPORTED|CONTRADICTED|UNVERIFIED)", line, re.IGNORECASE)
                if match:
                    idx = int(match.group(1)) - 1
                    status = match.group(2).upper()
                    validation_map[idx] = status

            validated: List[Dict[str, Any]] = []
            for i, fact in enumerate(facts):
                fact_copy = dict(fact)
                status = validation_map.get(i, "UNVERIFIED")
                fact_copy["validation_status"] = status

                if status == "SUPPORTED":
                    fact_copy["confidence"] = min(1.0, fact.get("confidence", 0.5) + 0.2)
                elif status == "CONTRADICTED":
                    fact_copy["confidence"] = max(0.0, fact.get("confidence", 0.5) - 0.3)
                else:
                    fact_copy["confidence"] = fact.get("confidence", 0.5)

                validated.append(fact_copy)

            return validated

        # Heuristic: boost confidence for claims that share keywords with others
        validated: List[Dict[str, Any]] = []
        for i, fact in enumerate(facts):
            fact_copy = dict(fact)
            claim_words = set(re.findall(r"[a-zA-Z0-9]+", fact["claim"].lower()))
            supporting_count = 0

            for j, other in enumerate(facts):
                if i == j:
                    continue
                other_words = set(re.findall(r"[a-zA-Z0-9]+", other["claim"].lower()))
                overlap = len(claim_words & other_words)
                if overlap >= 3:
                    supporting_count += 1

            if supporting_count > 0:
                boost = min(0.3, supporting_count * 0.1)
                fact_copy["confidence"] = min(1.0, fact.get("confidence", 0.5) + boost)
                fact_copy["validation_status"] = "SUPPORTED"
            else:
                fact_copy["validation_status"] = "UNVERIFIED"

            validated.append(fact_copy)

        return validated

    async def _synthesize(
        self,
        validated_facts: List[Dict[str, Any]],
        question: str,
    ) -> str:
        """
        Phase 5: Synthesize validated facts into a coherent narrative.

        Args:
            validated_facts: Cross-validated fact dicts.
            question: The clarified research question.

        Returns:
            Synthesized text answering the question.
        """
        if not validated_facts:
            return "No validated facts available for synthesis."

        if self.llm_fn is not None:
            # Sort by confidence descending
            sorted_facts = sorted(
                validated_facts,
                key=lambda f: f.get("confidence", 0),
                reverse=True,
            )
            facts_text = "\n".join(
                f"- [{f.get('validation_status', '?')}] (confidence: "
                f"{f.get('confidence', 0):.2f}) {f['claim']}"
                for f in sorted_facts
            )
            prompt = (
                "You are a research analyst. Based on the validated facts "
                "below, write a clear and comprehensive answer to the "
                "question. Cite facts where possible.\n\n"
                f"Question: {question}\n\n"
                f"Facts:\n{facts_text}"
            )
            return await self.llm_fn(prompt)

        # Heuristic: concatenate top facts as bullet points
        sorted_facts = sorted(
            validated_facts,
            key=lambda f: f.get("confidence", 0),
            reverse=True,
        )
        lines = [f"Research synthesis for: {question}\n"]
        for fact in sorted_facts[:10]:
            status = fact.get("validation_status", "?")
            conf = fact.get("confidence", 0)
            lines.append(f"- [{status}, {conf:.2f}] {fact['claim']}")

        return "\n".join(lines)

    async def _conclude(
        self,
        synthesis: str,
        question: str,
    ) -> Tuple[str, float]:
        """
        Phase 6: Produce a final conclusion with confidence score.

        Args:
            synthesis: The synthesized narrative from phase 5.
            question: The clarified research question.

        Returns:
            Tuple of (conclusion text, confidence score 0-1).
        """
        if not synthesis:
            return ("Unable to reach a conclusion due to insufficient data.", 0.0)

        if self.llm_fn is not None:
            prompt = (
                "Based on the following research synthesis, write a concise "
                "conclusion (2-4 sentences) answering the question. Then on a "
                "new line write 'CONFIDENCE: X.XX' where X.XX is your "
                "confidence from 0.00 to 1.00.\n\n"
                f"Question: {question}\n\n"
                f"Synthesis:\n{synthesis}"
            )
            response = await self.llm_fn(prompt)

            # Parse confidence from response
            confidence = 0.5
            conclusion_lines: List[str] = []
            for line in response.splitlines():
                conf_match = re.match(r"CONFIDENCE\s*:\s*([\d.]+)", line.strip(), re.IGNORECASE)
                if conf_match:
                    try:
                        confidence = float(conf_match.group(1))
                        confidence = max(0.0, min(1.0, confidence))
                    except ValueError:
                        confidence = 0.5
                else:
                    conclusion_lines.append(line)

            conclusion_text = "\n".join(conclusion_lines).strip()
            return (conclusion_text, confidence)

        # Heuristic: derive confidence from validated facts in phase_results
        phase_data = self.phase_results.get(
            ResearchPhase.CROSS_VALIDATION.value
        )
        if phase_data and phase_data.data:
            confidences = [
                f.get("confidence", 0.0) for f in phase_data.data
                if isinstance(f, dict)
            ]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        else:
            avg_confidence = 0.3

        conclusion_text = f"Based on the available evidence: {synthesis[:500]}"
        return (conclusion_text, round(avg_confidence, 2))


__all__ = [
    "ResearchPhase",
    "PhaseResult",
    "ResearchResult",
    "ResearchWorkflow",
]


if __name__ == "__main__":
    async def _demo() -> None:
        """Run a quick demo with no external dependencies."""
        workflow = ResearchWorkflow()
        result = await workflow.execute("What causes aurora borealis?")

        print("=== ResearchWorkflow Demo ===")
        print(f"Question:  {result.question}")
        print(f"Clarified: {result.clarified_question}")
        print(f"Sources:   {len(result.sources)}")
        print(f"Facts:     {len(result.facts)}")
        print(f"Validated: {len(result.validated_facts)}")
        print(f"Confidence: {result.confidence:.2f}")
        print(f"Duration:  {result.total_duration_ms:.1f}ms")
        print()

        for phase_name, pr in result.phase_results.items():
            print(f"  Phase '{phase_name}': {pr.status} ({pr.duration_ms:.1f}ms)")
            if pr.notes:
                print(f"    Notes: {pr.notes}")

        print("\n\u2705 ResearchWorkflow demo passed!")

    asyncio.run(_demo())
