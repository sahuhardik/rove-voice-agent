"""All settings, from the environment, with working defaults."""
import os

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

#: Live diagnostic agent. Claude Sonnet 4.6 (enabled on the account 2026-11-12).
#: Fallback if Claude is unavailable: "moonshotai.kimi-k2.5" (the model v2 was first built on).
AGENT_MODEL = os.environ.get("ROVE_AGENT_MODEL", "us.anthropic.claude-sonnet-4-6")
#: Fast classifier used as a safety backstop next to the rules.
FAST_MODEL = os.environ.get("ROVE_FAST_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
#: Used automatically when the model above is refused (access, payment, throttling).
#: Claude on Bedrock is an AWS Marketplace subscription; on 2026-11-12 it failed with
#: INVALID_PAYMENT_INSTRUMENT until the account has a valid payment method.
AGENT_FALLBACK_MODEL = os.environ.get("ROVE_AGENT_FALLBACK_MODEL", "moonshotai.kimi-k2.5")
FAST_FALLBACK_MODEL = os.environ.get("ROVE_FAST_FALLBACK_MODEL", "us.amazon.nova-2-lite-v1:0")
#: Offline work: compiling knowledge packs and judging eval conversations.
#: Default is Kimi K2.5 because Claude needs the Anthropic use-case form on this
#: account; in a trial on the R3 pack it was the most complete with no unsupported
#: numbers. Set to "us.anthropic.claude-opus-4-6-v1" once Claude is enabled.
OFFLINE_MODEL = os.environ.get("ROVE_OFFLINE_MODEL", "moonshotai.kimi-k2.5")

POLLY_VOICE = os.environ.get("ROVE_POLLY_VOICE", "Joanna")
POLLY_ENGINE = os.environ.get("ROVE_POLLY_ENGINE", "neural")

#: Local Ollama server, used for model ids like "ollama:qwen3:8b".
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_NUM_CTX = int(os.environ.get("ROVE_OLLAMA_CTX", "16384"))
#: Send the model a small relevant slice of the packs instead of everything (needed for slow local models).
COMPACT_CONTEXT = os.environ.get("ROVE_COMPACT_CONTEXT", "1" if "ollama:" in AGENT_MODEL else "0") == "1"
