import json
from src.services.ai.base import get_ai_client

async def improve_text(text: str, context: str = "resume bullet point") -> str:
    print(f"DEBUG: improve_text started. Context: {context}, Text length: {len(text)}")
    client, model = get_ai_client(provider="openai")
    print(f"DEBUG: Using client with model: {model}")
    
    # If the text looks like JSON (starts with {), we tell the AI to maintain that structure
    is_json_request = text.strip().startswith('{')
    
    # Detection of intent from context
    ctx_lower = context.lower()
    is_translation = "translate" in ctx_lower or "action: translate" in ctx_lower
    is_optimization = "optimize" in ctx_lower or "action: optimize" in ctx_lower
    
    # Extract Job Description if optimization
    job_description = ""
    if is_optimization and ", jd: " in ctx_lower:
        # Simple extraction from the formatted context string: "Action: ..., Lang: ..., JD: ..."
        jd_marker = "jd: "
        jd_index = ctx_lower.find(jd_marker)
        if jd_index != -1:
            job_description = context[jd_index + len(jd_marker):].strip()
    
    # Determine target language for instructions
    target_lang = "the original language of the input"
    if "lang: es" in ctx_lower: target_lang = "Spanish"
    elif "lang: en" in ctx_lower: target_lang = "English"
    elif "lang: pt" in ctx_lower: target_lang = "Portuguese"
    
    if is_translation:
        system_prompt = (
            f"You are a professional translator and resume expert. Your goal is to translate the CV content "
            f"into {target_lang} while maintaining the professional tone, context, and impact. "
            "Ensure technical terms are translated correctly for the target industry. "
            "\n\nCRITICAL: You MUST keep the EXACT same number of items in each section. Do NOT skip, summarize, or remove any experience, education, project, or skill items. This is a 1:1 translation."
        )
    elif is_optimization and job_description:
        system_prompt = (
            f"You are an expert resume optimizer and recruiter. Your goal is to rewrite the resume content in {target_lang} "
            f"to perfectly align with the following Job Description:\n\n--- JOB DESCRIPTION ---\n{job_description}\n---\n\n"
            "Instructions:\n"
            "1. Identify key skills, keywords, and technical requirements (like Python, AI, React, etc.) from the Job Description.\n"
            "2. Seamlessly integrate these keywords into the resume's summary, experience descriptions, and skills list.\n"
            "3. Highlight past responsibilities and achievements that directly match the needs of this specific role.\n"
            "4. Maintain a professional, metric-driven, and high-impact tone.\n"
            "5. PRESERVE CONTENT: Do NOT delete entire sections or items unless they are completely irrelevant. Maintain the richness of the resume while tailoring the focus.\n"
            f"6. IMPORTANT: The entire response MUST be in {target_lang}."
        )
    else:
        system_prompt = (
            f"You are an expert resume copywriter. Your goal is to rewrite resume content in {target_lang} "
            "to be more professional, impactful, and metric-driven. Improve grammar and ensure the use of "
            "strong action verbs. Maintain the original meaning but enhance the delivery. "
            f"IMPORTANT: You MUST write the response in {target_lang}."
        )
    
    if is_json_request:
        if is_translation:
            system_prompt += (
                f"\n\nIMPORTANT: The input text is a JSON representation of a CV. "
                f"You MUST return ONLY a valid JSON object with the exact same structure as the input, "
                f"but with ALL strings (personal details EXCEPT proper names, summary, roles, descriptions, skills) translated into {target_lang}. "
                "Do not include any prose, explanations, or markdown code blocks. "
                "Just the raw JSON object."
            )
        elif is_optimization and job_description:
            system_prompt += (
                f"\n\nIMPORTANT: The input text is a JSON representation of a CV. "
                f"You MUST return ONLY a valid JSON object with the exact same structure as the input, "
                f"but with the content tailored to match the Job Description while remaining in {target_lang}. "
                "Ensure that all sections (summary, experience, skills) reflect the requirements of the job."
                "Do not include any prose, explanations, or markdown code blocks. "
                "Just the raw JSON object."
            )
        else:
            system_prompt += (
                f"\n\nIMPORTANT: The input text is a JSON representation of a CV. "
                f"You MUST return ONLY a valid JSON object with the exact same structure as the input, "
                f"but with the content (summary, experience descriptions, etc.) improved while remaining in {target_lang}. "
                "Do not include any prose, explanations, or markdown code blocks. "
                "Just the raw JSON object."
            )

    print(f"DEBUG: Calling AI API (is_json={is_json_request})...")
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context: {context}\nText to improve: {text}"}
        ],
        response_format={'type': 'json_object'} if is_json_request else None
    )
    
    print("DEBUG: AI API call successful.")
    return response.choices[0].message.content
