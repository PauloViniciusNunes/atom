import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.agent.config.settings import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
    TEMPERATURE,
    NUM_PREDICT,
    REQUEST_TIMEOUT,
)


class Agent:
    """Interface de comunicação entre o Atom e o Ollama."""

    TEST_RESPONSE = "D.U.M.P. Test mode.... finish..."

    def __init__(self, test_mode: bool = False):
        self.host = OLLAMA_HOST.rstrip("/")
        self.model = OLLAMA_MODEL
        self.temperature = TEMPERATURE
        self.num_predict = NUM_PREDICT
        self.timeout = REQUEST_TIMEOUT
        self.test_mode = test_mode

    def send(self, messages: list[dict[str, str]]) -> str:
        """
        Envia mensagens ao modelo e retorna a resposta textual.

        Quando test_mode=True, não ativa o Ollama e retorna
        uma resposta fixa para testes.
        """
        if self.test_mode:
            return self.TEST_RESPONSE

        if not isinstance(messages, list) or not messages:
            raise ValueError("messages deve ser uma lista não vazia.")

        for message in messages:
            if (
                not isinstance(message, dict)
                or message.get("role")
                not in ("system", "user", "assistant")
                or not isinstance(message.get("content"), str)
            ):
                raise ValueError(
                    "Cada mensagem deve conter role e content válidos."
                )

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.num_predict,
            },
        }

        request = Request(
            url=f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))

        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama retornou HTTP {error.code}: {details}"
            ) from error

        except (URLError, TimeoutError) as error:
            raise RuntimeError(
                f"Não foi possível comunicar com o Ollama: {error}"
            ) from error

        except json.JSONDecodeError as error:
            raise RuntimeError(
                "O Ollama retornou uma resposta JSON inválida."
            ) from error

        message = result.get("message")

        if not isinstance(message, dict) or not isinstance(
            message.get("content"), str
        ):
            raise RuntimeError(
                "A resposta do Ollama não contém o texto esperado."
            )

        return message["content"]
