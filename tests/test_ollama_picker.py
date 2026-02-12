from alter.core.llm.ollama import OllamaModel, choose_best_model


def test_choose_best_model_prefers_local_and_strong_models():
    models = [
        OllamaModel(name="qwen3-coder:480b-cloud", size=None),
        OllamaModel(name="kimi-k2-thinking:cloud", size=None),
        OllamaModel(name="llama3.1:8b", size=4_900_000_000),
        # Qwen 2.5: Weight 112 * 10 + ~5 = 1125
        OllamaModel(name="qwen2.5:7b-instruct-q5_K_M", size=5_400_000_000),
        # GPT-OSS: Weight 110 * 10 + ~12 = 1112
        OllamaModel(name="gpt-oss:20b", size=13_000_000_000),
    ]
    # Qwen 2.5 is newer and preferred over GPT-OSS despite being smaller, 
    # due to the updated heuristics.
    assert choose_best_model(models) == "qwen2.5:7b-instruct-q5_K_M"


def test_choose_best_model_prefers_deepseek_and_qwen_coder():
    models = [
        OllamaModel(name="llama3.1:8b", size=4_900_000_000),
        OllamaModel(name="qwen2.5-coder:7b", size=5_100_000_000),
        OllamaModel(name="deepseek-coder-v2:16b", size=9_800_000_000),
        OllamaModel(name="gpt-oss:20b", size=13_000_000_000),
    ]
    # DeepSeek Coder V2 (weight 130) > GPT-OSS (weight 110)
    assert choose_best_model(models) == "deepseek-coder-v2:16b"

    models_no_deepseek = [
        OllamaModel(name="llama3.1:8b", size=4_900_000_000),
        OllamaModel(name="qwen2.5:7b", size=5_100_000_000),
        OllamaModel(name="gpt-oss:20b", size=13_000_000_000),
    ]
    # Qwen 2.5 (112) > GPT-OSS (110)
    assert choose_best_model(models_no_deepseek) == "qwen2.5:7b"
