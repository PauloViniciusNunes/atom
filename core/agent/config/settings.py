
import os

# Ollama connection
OLLAMA_HOST = os.getenv(
    "OLLAMA_HOST",
    "http://localhost:11434",
)

# Model selection
OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "granite4.1:8b",
)

# Inference parameters
TEMPERATURE = float(
    os.getenv("OLLAMA_TEMPERATURE", "0.2")
)

NUM_PREDICT = int(
    os.getenv("OLLAMA_NUM_PREDICT", "2048")
)

# Communication
REQUEST_TIMEOUT = float(
    os.getenv("OLLAMA_TIMEOUT", "120")
)
