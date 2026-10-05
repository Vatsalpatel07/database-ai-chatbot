import os

from dotenv import load_dotenv
from openai import OpenAI


class DeepSeekClient:
    """
    Thin wrapper around the DeepSeek API.

    JSON generation is used for structured planning/schema work.
    Text generation is used only for the final user-facing answer.
    """

    def __init__(self, model: str | None = None):
        load_dotenv()

        api_key = os.getenv("DEEPSEEK_API_KEY")

        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY was not found. "
                "Add it to the .env file."
            )

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )

        self.model = model or os.getenv(
            "DEEPSEEK_MODEL",
            "deepseek-v4-flash",
        )

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            response_format={
                "type": "json_object"
            },
            stream=False,
        )

        content = (
            response
            .choices[0]
            .message
            .content
        )

        if not content:
            raise RuntimeError(
                "DeepSeek returned empty content."
            )

        return content

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """
        Generate ordinary natural-language text.

        This method is deliberately separate from generate_json()
        because final answers are prose, not structured QueryPlans.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            stream=False,
        )

        content = (
            response
            .choices[0]
            .message
            .content
        )

        if not content:
            raise RuntimeError(
                "DeepSeek returned empty content."
            )

        return content.strip()
