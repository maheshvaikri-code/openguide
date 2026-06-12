"""OpenAI SDK drop-in: point base_url at the proxy, add one header.

Zero app logic changes — governance activates purely through configuration.
Run the proxy (see deploy/compose), then:

    python integrations/openai_sdk_example.py
"""
from __future__ import annotations

import os


def main() -> None:
    from openai import OpenAI  # pip install openai

    # 1. point the SDK at the OpenGuide proxy instead of the provider
    client = OpenAI(
        base_url=os.environ.get("OPENGUIDE_PROXY", "http://localhost:8088") + "/v1",
        api_key=os.environ.get("OPENAI_API_KEY", "sk-..."),
    )

    # 2. activate a contract with one default header (the only change)
    contract_hash = os.environ["OPENGUIDE_CONTRACT"]   # sha256:... from the registry
    resp = client.chat.completions.create(
        model="openai:gpt-4o",
        messages=[{"role": "user", "content": "Refactor the config loader; keep tests green."}],
        extra_headers={
            "X-OpenGuide-Contract": contract_hash,
            "X-OpenGuide-Session": "demo-conversation-1",
        },
    )
    print(resp.choices[0].message.content)
    # behavioral state is now in your OTel backend and at
    #   GET {proxy}/v1/openguide/sessions/demo-conversation-1


if __name__ == "__main__":
    main()
