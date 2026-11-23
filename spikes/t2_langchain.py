"""Test 2: LangChain (LCEL) chain on the local Qwen: prompt | model | JSON parser."""
import _offline  # noqa: F401  (no outbound traffic; see lrt_offline.py)
import time

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from common import BASE_URL, MODEL, REQUEST_S5, result


def run():
    t0 = time.time()
    llm = ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key="local", temperature=0, max_tokens=300)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You extract fields from laboratory test requests. Answer with JSON only."),
        ("user", "Request: {request}\n\nReturn only JSON with keys test_type (one of warpage_reflow, thermal_cycling, "
                 "flatness_rt; the first test requested), samples (integer) and missing (list of inputs the lab still needs)."),
    ])
    chain = prompt | llm | JsonOutputParser()
    out = chain.invoke({"request": REQUEST_S5})
    ok = isinstance(out, dict) and out.get("test_type") in {"warpage_reflow", "thermal_cycling", "flatness_rt"} \
        and isinstance(out.get("samples"), int)
    return result("2. LangChain LCEL chain with structured (JSON) output", ok, t0, output=out)


if __name__ == "__main__":
    print(run())
