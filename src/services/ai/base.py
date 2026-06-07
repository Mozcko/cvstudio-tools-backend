from openai import AsyncOpenAI
from src.core.config import settings

# DeepSeek Client
deepseek_client = None
if settings.DEEPSEEK_API_KEY:
    deepseek_client = AsyncOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL
    )

# OpenAI Client
openai_client = None
if settings.OPENAI_API_KEY:
    openai_client = AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY
    )

def get_ai_client(provider="openai"): # Force default to openai
    print(f"DEBUG: get_ai_client called with provider={provider}")
    print(f"DEBUG: deepseek_client exists={bool(deepseek_client)}")
    print(f"DEBUG: openai_client exists={bool(openai_client)}")
    
    if provider == "openai" or not deepseek_client:
        if not openai_client:
            raise ValueError("OpenAI API key is missing.")
        return openai_client, "gpt-4o-mini"
    
    # Even if deepseek is requested, if it's failing, we might want to override
    # But for now let's respect it if explicitly called with "deepseek"
    if provider == "deepseek":
        if not deepseek_client:
            raise ValueError("DeepSeek API key is missing.")
        return deepseek_client, "deepseek-chat"
        
    return openai_client, "gpt-4o-mini"
