from src.services.ai.base import get_ai_client
from src.utils.sanitizer import mask_cv_pii
import json
from datetime import datetime

async def generate_cover_letter(cv_data: dict, job_description: str) -> str:
    client, model = get_ai_client(provider="openai")
    
    # Extract real personal info for header (without giving it to AI)
    personal = cv_data.get("personal", {})
    name = personal.get("name", "[Your Name]")
    email = personal.get("email", "[Your Email]")
    phone = personal.get("phone", "[Your Phone]")
    city = personal.get("city", "[Your City]")
    
    # Sanitize PII before sending to LLM for the narrative generation
    sanitized_cv = mask_cv_pii(cv_data)
    
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system", 
                "content": (
                    "You are an expert recruiter and career coach. Write a highly tailored, compelling, and professional cover letter body. "
                    "Focus strictly on the professional narrative, highlighting relevant experiences and skills from the resume that align with the job description. "
                    "\n\nIMPORTANT: Do NOT include your own contact information header (Name, Email, Date, etc.) at the top. "
                    "Start directly with the salutation (e.g., 'Dear Hiring Manager,' or 'To the [Company Name] Team,')."
                )
            },
            {"role": "user", "content": f"Resume Data: {json.dumps(sanitized_cv)}\n\nJob Description: {job_description}"}
        ]
    )
    
    letter_body = response.choices[0].message.content
    
    # Programmatically construct the professional header
    header = f"{name}\n"
    if city: header += f"{city}\n"
    header += f"{email}\n{phone}\n"
    header += f"{datetime.now().strftime('%B %d, %Y')}\n\n"
    
    # Combine header with the AI-generated body
    return f"{header}{letter_body}"
