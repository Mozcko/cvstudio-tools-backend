from src.services.ai.base import get_ai_client
from src.utils.sanitizer import mask_cv_pii
import json

async def simulate_ats(cv_data: dict, job_description: str) -> dict:
    client, model = get_ai_client(provider="openai")
    
    # Sanitize PII before sending to LLM
    sanitized_cv = mask_cv_pii(cv_data)
    
    system_prompt = (
        "You are an advanced Applicant Tracking System (ATS) and Senior Recruiter. "
        "Analyze the provided resume against the job description with extreme precision. "
        "You MUST return a JSON object with the following EXACT structure:\n\n"
        "{\n"
        "  \"final_ats_score\": number (0-100),\n"
        "  \"overall_interview_probability\": number (0-100),\n"
        "  \"tier_classification\": \"Top Match\" | \"Competitive\" | \"Needs Improvement\" | \"Weak Match\",\n"
        "  \"hard_requirements_analysis\": [\n"
        "    { \"requirement\": \"string\", \"status\": \"match\" | \"missing\" | \"partial\", \"comment\": \"string\" }\n"
        "  ],\n"
        "  \"missing_keywords\": [\"string\"],\n"
        "  \"top_improvement_actions\": [\"string\"]\n"
        "}\n\n"
        "Instructions:\n"
        "- final_ats_score: How well the resume matches technical keywords and experience.\n"
        "- overall_interview_probability: Likelihood of being called for an interview based on the overall profile.\n"
        "- hard_requirements_analysis: Evaluate specific must-haves (years of experience, specific tech stack, degree).\n"
        "- missing_keywords: List critical technical or soft skills found in the JD but not in the resume.\n"
        "- top_improvement_actions: Provide actionable steps to increase the score."
    )

    response = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Resume Data: {json.dumps(sanitized_cv)}\n\nJob Description: {job_description}"}
        ]
    )
    
    return json.loads(response.choices[0].message.content)
