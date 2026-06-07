from src.services.ai.base import get_ai_client

async def translate_text(text: str, target_language: str) -> str:
    client, model = get_ai_client(provider="openai")
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": f"You are a professional translator. Translate the following text into {target_language}. Maintain the original tone and professional context."},
            {"role": "user", "content": text}
        ]
    )
    return response.choices[0].message.content
