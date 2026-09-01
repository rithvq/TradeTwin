from abc import ABC, abstractmethod

import httpx

from app.config import settings


class LLMGateway(ABC):
    name: str
    model: str

    @abstractmethod
    def classification_hints(self, product_name: str, product_description: str) -> list[str]:
        raise NotImplementedError


class MockLLMGateway(LLMGateway):
    name = "mock"
    model = "local-keyword-hints"

    def classification_hints(self, product_name: str, product_description: str) -> list[str]:
        text = f"{product_name} {product_description}".lower()
        hints = []
        keyword_groups = {
            "lithium battery": ["lithium", "battery", "batteries", "accumulator"],
            "consumer electronics": ["electronics", "device", "retail"],
            "phone": ["phone", "smartphone", "mobile"],
            "television": ["television", "display", "monitor"],
            "packing": ["pack", "package", "packing"],
        }
        for hint, keywords in keyword_groups.items():
            if any(keyword in text for keyword in keywords):
                hints.append(hint)
        return hints or text.split()[:4]


class OpenAICompatibleGateway(LLMGateway):
    name = "openai-compatible"

    def __init__(self) -> None:
        self.model = settings.llm_model

    def classification_hints(self, product_name: str, product_description: str) -> list[str]:
        if not settings.llm_api_key:
            return MockLLMGateway().classification_hints(product_name, product_description)

        response = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Return comma-separated product classification hints only. "
                            "Do not cite private customs outcomes."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"{product_name}\n{product_description}",
                    },
                ],
                "temperature": 0,
            },
            timeout=15,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return [item.strip().lower() for item in content.split(",") if item.strip()]


def get_gateway() -> LLMGateway:
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleGateway()
    return MockLLMGateway()
