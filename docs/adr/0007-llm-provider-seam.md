# The AI assistant is built behind a provider seam, with one implementation

The teacher AI assistant currently talks to exactly one LLM vendor (Google AI
Studio's Gemini, over its REST API). Calling that API directly from the
assistant's tool loop and SSE handling would be less code today, but LLM
vendors are a fast-moving, price- and capability-competitive space, model
names get deprecated out from under a hardcoded integration, and provider
outages need a fallback path — all reasons a hardcoded single vendor becomes
expensive to change exactly when there's the most pressure to change it
quickly.

The decision is a small `LLMProvider` abstract interface (`ToolSpec` /
`ToolCall` / `ProviderReply`) that carries no vendor-specific naming or
behavior, with the one Gemini implementation living entirely behind it and a
single registry function reading an env var to pick the active provider.
Swapping or adding a backend costs one new file implementing the interface
plus one registry entry — nothing above that layer needs to change. The
trade-off this abstraction has to honor: reasoning models stamp each tool
call with a provider-specific signature and reject a request if that stamp
is missing, so the interface must let the provider's own opaque rendering of
its turn be replayed verbatim on the next round rather than reconstructed
from plain name/argument pairs — reconstructing it is what breaks multi-turn
tool use the moment a second vendor with this behavior is added.

Status: accepted.
