"""One short German prompt through a configured LLM provider; prints the measured metrics.

  python scripts/llm_smoke.py --provider apertus_aws
  SENTINEL_ALLOW_REMOTE_LLM=fictional_data_only python scripts/llm_smoke.py --provider openrouter --list-models
  SENTINEL_ALLOW_REMOTE_LLM=fictional_data_only python scripts/llm_smoke.py --provider openrouter --model qwen/qwen-2.5-72b-instruct

The prompt is generic and carries no project data. Remote providers are refused by the policy gate before any
network call unless the env var above is set and the model is on the provider's allowlist. Exit codes:
0 ok, 2 refused by the gate or the call failed. Keys are never printed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.llm import LLMError, ProviderNotPermitted, get_client  # noqa: E402

PROMPT = [{"role": "user", "content": "Antworte in einem kurzen Satz auf Deutsch: Was ist ein Passwort?"}]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", help="name from config/providers.yaml (default: the registry default)")
    ap.add_argument("--model", help="model id (remote providers: must be on the allowlist)")
    ap.add_argument("--list-models", action="store_true", help="GET /models, filtered to the provider's allowlist")
    ap.add_argument("--no-stream", action="store_true", help="plain request (no TTFT)")
    args = ap.parse_args(argv)
    try:
        client = get_client(args.provider, args.model, need_model=not args.list_models)
        spec = client.spec
        print(f"provider={spec.name} self_hosted={spec.self_hosted} model={client.model}")
        if args.list_models:
            served = set(client.list_models())
            if spec.allowed_models:
                found = [m for m in spec.allowed_models if m in served]
                missing = [m for m in spec.allowed_models if m not in served]
                print(f"catalog size: {len(served)}")
                print(f"allowlisted and served ({len(found)}):", *found, sep="\n  ")
                print(f"allowlisted but NOT in the catalog, unverified ({len(missing)}):", *missing, sep="\n  ")
            else:
                print(f"served ({len(served)}):", *sorted(served), sep="\n  ")
            return 0
        text, m = client.chat_with_metrics(PROMPT, max_tokens=80, stream=not args.no_stream)
    except ProviderNotPermitted as e:
        print(f"REFUSED by policy gate (no network call made): {e}", file=sys.stderr)
        return 2
    except LLMError as e:
        print(f"LLM call failed: {e}", file=sys.stderr)
        return 2
    print("answer:", text.strip()[:300])
    print(json.dumps(m.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
