"""
Local test suite network policy: nothing in this project calls out to the internet at run time.

Import this module before any ML or agent library. It switches off the outbound traffic those libraries
make by default: Hugging Face model and update checks, CrewAI and OpenTelemetry telemetry, LangSmith tracing.
The only network traffic left is on this computer: the browser to the local page server, and the
agents to the local Qwen server (127.0.0.1:8000).

One exception, on purpose: the first download of the models (Qwen, the embedding model) comes from
Hugging Face, the AI source chosen for this project. Run that once with LRT_ALLOW_DOWNLOAD=1; after that
the models load from the local cache and the suite runs with the network unplugged.
"""
import os

_ALWAYS = {
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "CREWAI_DISABLE_TELEMETRY": "true",
    "CREWAI_DISABLE_TRACKING": "true",
    "OTEL_SDK_DISABLED": "true",
    "LANGCHAIN_TRACING_V2": "false",
    "LANGSMITH_TRACING": "false",
    "ANONYMIZED_TELEMETRY": "False",
}
_NO_DOWNLOAD = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
}

for k, v in _ALWAYS.items():
    os.environ[k] = v
if os.environ.get("LRT_ALLOW_DOWNLOAD") != "1":
    for k, v in _NO_DOWNLOAD.items():
        os.environ[k] = v

LOOPBACK = ("127.0.0.1", "localhost", "::1")

# Never send local traffic through a proxy: a corporate proxy set in Windows or in HTTP(S)_PROXY would otherwise
# see request text on its way to the local model.
_np = [x for x in (os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "").split(",") if x.strip()]
os.environ["NO_PROXY"] = os.environ["no_proxy"] = ",".join(dict.fromkeys(_np + list(LOOPBACK)))
