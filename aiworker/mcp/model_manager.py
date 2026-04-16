import requests


class ModelManager:
    def __init__(self, model="gemma:7b"):
        self.model = model
        self.base_url = "http://127.0.0.1:11434"

    def generate(self, prompt: str) -> str:
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=60,
            )
            return response.json().get("response", "").strip()
        except Exception as e:
            return f"ERROR: {str(e)}"


model_manager = ModelManager()
