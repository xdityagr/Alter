import logging
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path.cwd() / "src"))

from alter.config import load_config
from alter.core.agents.search_pipeline import SearchPipeline
from alter.core.agents.surfer import SurferAgent

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_surf")

from alter.core.llm.ollama import OllamaLlm

def main():
    print('hi')
    cfg = load_config(None).config
    print(f"Loaded config. SearXNG URL: {cfg.web.searxng_base_url}")
    
    # Initialize real LLM
    print("Initializing Ollama (llama3.1:8b)...")
    try:
        llm = OllamaLlm(
            base_url=cfg.llm.ollama_base_url,
            model="llama3.1:8b",
            timeout_s=120
        )
    except Exception as e:
        print(f"Failed to init Ollama: {e}")
        return

    agent = SurferAgent(cfg, headless=True)
    
    # Wrapper for the agent
    def real_llm_generate(system_prompt, user_prompt):
        return llm.generate(system_prompt=system_prompt, user_prompt=user_prompt)
    
    print("\n--- Testing DATE Awareness (Real LLM) ---")
    try:
        # 2025 Oscars should be in the past relative to Feb 2026
        res = agent.surf("Who won the Best Picture Oscar in 2025?", mode="fast", llm_generate_fn=real_llm_generate)
        print(f"DATE Result:\n{res}")
    except Exception as e:
        print(f"DATE Mode Failed: {e}")

    print("\n--- Testing WEATHER Accuracy (Real LLM) ---")
    try:
        res = agent.surf("current weather in Tokyo right now in celsius", mode="fast", llm_generate_fn=real_llm_generate)
        print(f"WEATHER Result:\n{res}")
    except Exception as e:
        print(f"WEATHER Mode Failed: {e}")

if __name__ == "__main__":
    main()
