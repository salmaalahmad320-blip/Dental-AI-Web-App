import os
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


def _local_report(detections: list[dict]) -> str:
    """
    Local fallback report generated without OpenAI.
    """

    counts = Counter(item["class"] for item in detections)
    summary = (
        "No supported dental findings were detected above the selected "
        "confidence threshold."
        if not detections
        else "The analysis identified "
        + ", ".join(f"{count} {name}" for name, count in counts.items())
        + "."
    )
    findings = (
        "No target findings were identified in this analysis."
        if not detections
        else "\n".join(
            f"- {item['class']}: {item['confidence']:.2f}% confidence "
            f"at bounding box {item['bbox']}"
            for item in detections
        )
    )

    return (
        "AI Preliminary Report (Local Mode)\n\n"

        "Summary\n"
        f"{summary}\n\n"

        "Detected findings\n"
        f"{findings}\n\n"

        "Confidence level\n"
        "Confidence reflects the trained model's estimate "
        "and is not a clinical certainty.\n\n"

        "Possible clinical considerations\n"
        "Findings should be correlated with the full radiograph, "
        "patient history, and clinical examination.\n\n"

        "Recommended next steps\n"
        "Have a qualified dentist or oral radiologist review "
        "the original image and determine appropriate follow-up.\n\n"

        "Disclaimer\n"
        "This is a preliminary AI-assisted analysis and does not "
        "claim a final diagnosis. Dentist evaluation is required."
    )


def generate_report(detections: list[dict]) -> str:
    """
    Generate report using OpenAI when configured, otherwise use the local report.
    """

    api_key = os.getenv("OPENAI_API_KEY")

    # No API key
    if not api_key:
        return _local_report(detections)

    try:
        from openai import OpenAI

        findings = "\n".join(
            f"""
Class: {item['class']}
Confidence: {item['confidence']:.2f}%
Bounding box: {item['bbox']}
"""
            for item in detections
        )

        if not findings:
            findings = "No findings detected above threshold."

        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model=os.getenv(
                "OPENAI_MODEL",
                "gpt-4.1-mini"
            ),

            input=f"""
You are an AI dental radiology reporting assistant helping a dentist.

Write a concise, case-specific preliminary interpretation based ONLY on the detection
results below. The application calculates all numerical summary values separately; do
not calculate, estimate, aggregate, or correct any numerical values.

Detected AI findings:
{findings}

For each detected item, explain only what that detected class may represent in cautious
clinical language, mention its supplied confidence and bounding box, and suggest review
of that region. Distinguish high-confidence and low-confidence findings without inventing
additional findings.
If multiple findings exist, distinguish them clearly instead of combining them into one generic statement.
If no findings exist, clearly state that no supported target was detected above the selected threshold.

Use this structure:

1. Summary
2. Detected Findings
3. Confidence Interpretation
4. Possible Clinical Considerations
5. Recommended Next Steps
6. Disclaimer

Rules:
- Use only the classes and values provided above.
- Never claim certainty or a final diagnosis.
- A detected Filling does not establish active caries.
- An Implant may be discussed only when Implant is explicitly listed as a detected class.
- Do not state or imply implant integration, implant position, stability, or placement quality; the model detects only the Implant class.
- Do not describe a condition that is not in the detection list.
- Do not calculate the total, class counts, average confidence, or confidence-band counts.
- Do not provide medication, surgery, extraction, replacement, removal, or any other treatment recommendation or treatment plan.
- Use review or follow-up suggestions only; do not call them treatment recommendations.
- Never invent tooth numbers.
- Never claim implant integration, implant position, bone loss, infection, or other characteristics not measured by the model.
- Explain that dentist evaluation is required.
- Recommend review against the original radiograph by a qualified dental professional.
- Use professional medical language.
- Keep the report concise and clear.
"""
        )

        return (
            "AI Generated Report (OpenAI)\n\n"
            + response.output_text
        )

    except Exception:
        return _local_report(detections)