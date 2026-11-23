"""Test 1: the local Qwen answers through an OpenAI-compatible API (openai SDK)."""
import _offline  # noqa: F401  (no outbound traffic; see lrt_offline.py)
import time

from openai import OpenAI

from common import BASE_URL, MODEL, result


def run():
    t0 = time.time()
    c = OpenAI(base_url=BASE_URL, api_key="local")
    ids = [m.id for m in c.models.list().data]
    a = c.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                                  max_tokens=10, temperature=0).choices[0].message.content
    b = c.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": "Count from 1 to 10, separated by commas."}],
                                  max_tokens=60, temperature=0, stop=["5"]).choices[0].message.content
    ok = MODEL in ids and "OK" in (a or "").upper() and "6" not in (b or "")
    return result("1. Local Qwen served as an OpenAI-compatible API", ok, t0,
                  models=ids, reply=a, stop_test=f"stop at '5' returned: {b!r}")


if __name__ == "__main__":
    print(run())
