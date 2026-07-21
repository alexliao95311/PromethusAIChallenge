import os

# chains/debater_chain.py (imported by services.lesson_generation) requires
# OPENROUTER_API_KEY to be set at import time. Tests never make a real
# OpenRouter call (LLM calls are mocked), so a dummy value is enough.
os.environ.setdefault("OPENROUTER_API_KEY", "test-dummy-key")
