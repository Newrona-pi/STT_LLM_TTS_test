import os
import openai
from dotenv import load_dotenv

load_dotenv()

openai.api_key = os.environ.get("OPENAI_API_KEY")

def extract_topic(text: str) -> str:
    """
    Extract the main topic/noun from the user's question.
    Example: "What are the benefits?" -> "Benefits" (or "Fukuri Kousei" in JP)
    Keep it short (noun only).
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Extract the main topic from the user's question in Japanese. Output ONLY the noun/topic. No extra words."},
                {"role": "user", "content": f"Extract topic from: {text}"}
            ],
            max_tokens=30,
            temperature=0
        )
        topic = response.choices[0].message.content.strip()
        return topic
    except Exception as e:
        print(f"[ERROR] LLM Error: {e}")
        return "ご質問" # Fallback
