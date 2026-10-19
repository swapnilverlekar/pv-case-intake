"""One place to build the chat model, so every node uses the same settings."""

from langchain_anthropic import ChatAnthropic

from pv_agent import config


def chat():
    """The plain chat model (tool calling for the follow-up planner)."""
    return ChatAnthropic(
        model=config.MODEL,
        max_tokens=config.MAX_TOKENS,
        output_config={"effort": config.EFFORT},
        betas=["server-side-fallback-2026-07-01"],
        model_kwargs={"fallbacks": "default"},
        default_headers={"Accept-Encoding": "gzip"},
    )


def structured(schema, model=None):
    """A model call that returns `schema` via native structured output.
    (json_schema, not tool calling: Sonnet 5.5 rejects forced tool choice.)"""
    llm = ChatAnthropic(
        model=model or config.MODEL,
        max_tokens=config.MAX_TOKENS,
        output_config={"effort": config.EFFORT},
        betas=["server-side-fallback-2026-07-01"],
        model_kwargs={"fallbacks": "default"},
        # gzip only: Anaconda's Brotli 1.0.9 breaks the SDK's response decoding.
        default_headers={"Accept-Encoding": "gzip"},
    )
    return llm.with_structured_output(schema, method="json_schema")


def norm(text):
    """Comparison form for quote checks: straight quotes, lowercase, single spaces."""
    text = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.lower().split())


def is_quote_of(quote, source):
    return bool(quote) and norm(quote) in norm(source)
