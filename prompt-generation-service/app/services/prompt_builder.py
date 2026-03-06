"""Prompt builder for blast-radius analysis.

Constructs a system + user message pair from a prediction result
payload, ready for submission to an LLM provider service.
"""

from __future__ import annotations

from app.models import LLMPromptPayload, PromptMessage

SYSTEM_PROMPT = (
    "You are a blast-radius analyst for a software engineering platform called TraceRat. "
    "Given information about a pull request — including its risk score, risk level, "
    "affected components, and historically similar PRs — produce a concise, actionable "
    "blast-radius report.\n\n"
    "Your report MUST use Markdown and include the following sections:\n"
    "1. **Summary** — One-paragraph overview of the change risk.\n"
    "2. **Affected Components** — Table with columns: Component, Impact Score, "
    "Relationship, Traffic.\n"
    "3. **Historical Context** — Bullet list of similar past PRs and their outcomes.\n"
    "4. **Recommendations** — Numbered list of concrete mitigation actions the author "
    "should take before merging.\n\n"
    "Keep the tone professional and direct.  Do NOT include information you were not given."
)


def _format_affected_components(components: list[dict]) -> str:
    """Format affected components as a Markdown table snippet for the user prompt."""
    if not components:
        return "No affected components identified."

    lines = ["| Component | Impact Score | Relationship | Traffic |"]
    lines.append("| --- | --- | --- | --- |")
    for comp in components:
        name = comp.get("name", "unknown")
        score = comp.get("impact_score", 0.0)
        rel = comp.get("relationship", "transitive")
        traffic = comp.get("traffic_volume") or "N/A"
        lines.append(f"| {name} | {score:.2f} | {rel} | {traffic} |")
    return "\n".join(lines)


def _format_similar_prs(similar_prs: list[str | dict]) -> str:
    """Format similar PRs as a bullet list."""
    if not similar_prs:
        return "No historically similar PRs found."

    lines: list[str] = []
    for item in similar_prs:
        if isinstance(item, dict):
            repo = item.get("repo_full_name", "")
            pr_num = item.get("pr_number", "")
            title = item.get("title", "")
            outcome = item.get("outcome", "unknown")
            similarity = item.get("similarity_score", 0.0)
            lines.append(
                f"- **{repo}#{pr_num}** — {title} "
                f"(outcome: {outcome}, similarity: {similarity:.2f})"
            )
        else:
            # Plain string URL
            lines.append(f"- {item}")

    return "\n".join(lines)


def _build_user_prompt(prediction: dict) -> str:
    """Assemble the user message from the prediction payload."""
    event_id = prediction.get("event_id", "unknown")
    repo = prediction.get("repo_full_name", "unknown")
    pr_number = prediction.get("pr_number", 0)
    risk_score = prediction.get("risk_score", 0.0)
    risk_level = prediction.get("risk_level", "UNKNOWN")
    explanation = prediction.get("explanation", "")
    affected = prediction.get("affected_components", [])
    similar = prediction.get("similar_prs", [])
    traffic_impact = prediction.get("traffic_impact") or "N/A"
    recommendations = prediction.get("recommendations", [])

    sections = [
        f"## Pull Request: {repo}#{pr_number}",
        f"Event ID: {event_id}",
        f"Risk Score: {risk_score:.2f}",
        f"Risk Level: {risk_level}",
        "",
    ]

    if explanation:
        sections.append(f"### Explanation\n{explanation}")
        sections.append("")

    sections.append(f"### Affected Components\n{_format_affected_components(affected)}")
    sections.append("")
    sections.append(f"Traffic Impact: {traffic_impact}")
    sections.append("")
    sections.append(f"### Similar Past PRs\n{_format_similar_prs(similar)}")
    sections.append("")

    if recommendations:
        rec_lines = [f"{i + 1}. {r}" for i, r in enumerate(recommendations)]
        sections.append("### Existing Recommendations\n" + "\n".join(rec_lines))
        sections.append("")

    sections.append(
        "Based on the information above, produce a blast-radius report."
    )

    return "\n".join(sections)


class PromptBuilder:
    """Builds LLM prompt payloads from prediction results.

    Stateless — each call to :meth:`build` produces an independent
    :class:`LLMPromptPayload`.
    """

    def build(self, prediction: dict) -> LLMPromptPayload:
        """Build a prompt payload from a raw prediction dict.

        Parameters
        ----------
        prediction:
            Deserialized ``PredictionOutput`` from the prediction-results topic.

        Returns
        -------
        LLMPromptPayload
            Ready-to-publish prompt payload with system + user messages.
        """
        system_msg = PromptMessage(role="system", content=SYSTEM_PROMPT)
        user_msg = PromptMessage(role="user", content=_build_user_prompt(prediction))

        return LLMPromptPayload(
            event_id=prediction.get("event_id", "unknown"),
            repo_full_name=prediction.get("repo_full_name", "unknown"),
            pr_number=prediction.get("pr_number", 0),
            installation_id=prediction.get("installation_id", 0),
            head_sha=prediction.get("head_sha", ""),
            risk_score=prediction.get("risk_score", 0.0),
            risk_level=prediction.get("risk_level", "UNKNOWN"),
            messages=[system_msg, user_msg],
            metadata={
                "source_topic": "prediction-results",
                "affected_component_count": len(
                    prediction.get("affected_components", [])
                ),
                "similar_pr_count": len(prediction.get("similar_prs", [])),
                "degraded": prediction.get("degraded", False),
                "original_prediction": prediction,
            },
        )
