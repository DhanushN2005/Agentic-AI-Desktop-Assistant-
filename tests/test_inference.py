from core.inference import CallableEngine, EngineRegistry, EngineResponse, recommend_model


def test_callable_engine_wraps_brain_ask():
    engine = CallableEngine("brain", lambda prompt, max_tokens=10: "answer")
    response = engine.generate([{"role": "user", "content": "hello"}])
    assert isinstance(response, EngineResponse)
    assert response.text == "answer"
    assert response.engine == "brain"


def test_registry_roundtrip_and_resolution():
    registry = EngineRegistry()
    engine = registry.register(CallableEngine("brain", lambda prompt, **_: "ok"))
    assert registry.get("brain") is engine
    assert registry.list_engines() == ["brain"]
    assert registry.resolve("brain") is engine


def test_model_recommendation_by_memory():
    assert recommend_model(ram_gb=32, vram_gb=12) == "qwen2.5-coder:7b"
    assert recommend_model(ram_gb=16) == "llama3.2:3b"
    assert recommend_model(ram_gb=4) == "llama3.2:1b"
