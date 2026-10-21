"""Shared fixtures. Every test here is offline and model-free:

- tracing is switched off before any pv_agent import (pv_agent.config would
  otherwise load LANGSMITH_TRACING=true from .env; load_dotenv never
  overrides a variable that is already set);
- every outgoing socket connection raises, so a test that reached the
  network would fail instead of calling an API;
- the model factories in pv_agent.llm raise if anything tries to build a
  client.
"""

import os
import socket

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

import pytest  # noqa: E402


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise NetworkBlocked("unit tests must not use the network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    import pv_agent.llm as llm

    def refuse(*args, **kwargs):
        raise AssertionError("unit tests must not build a model client")
    monkeypatch.setattr(llm, "chat", refuse)
    monkeypatch.setattr(llm, "structured", refuse)


# ---------------------------------------------------------------- builders


def quoted(value=None, quote=None, **extra):
    return {"value": value, "quote": quote, **extra}


def extraction(*, patient=True, reporter=True, reactions=True, reporter_type="consumer"):
    """A hand-built extraction result (what the extraction model would return,
    after code grounding). Each flag turns one validity element on or off."""
    return {
        "patient": {
            "reference": ({"text": "my mother", "relationship": "family_member", "quote": "my mother"}
                          if patient else {"text": None, "relationship": None, "quote": None}),
            "age": quoted(74.0 if patient else None, "who is 74" if patient else None, unit="years" if patient else None,
                          approximate=False),
            "sex": quoted("female" if patient else None, "my mother" if patient else None),
        },
        "reporter": {
            "type": reporter_type, "type_quote": None,
            "name": "Ann" if reporter else None, "name_quote": "Thanks, Ann" if reporter else None,
            "contact": "555-0199" if reporter else None, "contact_quote": "call me on 555-0199" if reporter else None,
        },
        "products": [],
        "reactions": ([{"reporter_words": "black, tarry stools", "quote": "she had black, tarry stools"}]
                      if reactions else []),
    }


def product(name="warfarin", maps_to="warfarin", role="suspected"):
    return {"name_as_written": name, "role_as_stated": role, "quote": f"takes {name}",
            "maps_to": maps_to, "matched_name": maps_to, "match_source": "label_generic" if maps_to else None}
