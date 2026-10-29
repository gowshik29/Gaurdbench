import requests

from .observability import traced
from .settings import get_settings


class OllamaClient:
    def __init__(self, model=None, base_url=None, timeout=180):
        settings = get_settings()
        self.model = model or settings["ollama_model"]
        self.base_url = (
            base_url or settings["ollama_base_url"]
        ).rstrip("/")
        if not self.model.strip():
            raise ValueError("Ollama model name cannot be empty")
        if timeout <= 0:
            raise ValueError("Ollama timeout must be positive")
        self.timeout = timeout

    @traced(run_type="llm")
    def chat(self, messages, temperature=0.0, format=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if format is not None:
            payload["format"] = format
        response = requests.post(
            self.base_url + "/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content")
        if not isinstance(content, str) or not content:
            raise ValueError("Ollama returned an empty or malformed chat response")
        return content
