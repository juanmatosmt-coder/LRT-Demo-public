"""Test 3: CrewAI role separation and task routing on the local Qwen (planner -> reviewer)."""
import _offline  # noqa: F401  (no outbound traffic; see lrt_offline.py)
import os
import time

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from crewai import LLM, Agent, Crew, Process, Task  # noqa: E402

from common import BASE_URL, MODEL, REQUEST_S5, result  # noqa: E402


def run():
    t0 = time.time()
    llm = LLM(model=MODEL, custom_openai=True, base_url=BASE_URL, api_key="local", temperature=0, max_tokens=700,
              context_window_size=32768)
    planner = Agent(role="Test planner", llm=llm, allow_delegation=False, verbose=False,
                    goal="Propose laboratory test plans that follow the lab procedures",
                    backstory="You plan reliability tests for connector housings. You propose options; you do not judge them.")
    reviewer = Agent(role="Plan reviewer", llm=llm, allow_delegation=False, verbose=False,
                     goal="Judge proposed test plans against the engineer's objective and the procedure rules",
                     backstory="You review test plans. Rules: at least 5 samples per test condition; no second reflow "
                               "profile on the same samples unless the engineer confirms it; precondition before each thermal test.")
    propose = Task(agent=planner, expected_output="Two numbered options, each with sample groups and step order",
                   description=f"Engineer request: {REQUEST_S5}\nThere are 10 housings. Propose two different test plans.")
    review = Task(agent=reviewer, context=[propose], expected_output="For each option: acceptable or not, and why; then the preferred option",
                  description="Review the proposed options against the rules and pick one.")
    crew = Crew(agents=[planner, reviewer], tasks=[propose, review], process=Process.sequential, verbose=False)
    crew.kickoff()
    a, b = (propose.output.raw if propose.output else ""), (review.output.raw if review.output else "")
    ok = len(a.strip()) > 20 and len(b.strip()) > 20
    return result("3. CrewAI planner and reviewer agents (role separation, task routing)", ok, t0,
                  planner_output=a[:1200], reviewer_output=b[:1200])


if __name__ == "__main__":
    print(run())
