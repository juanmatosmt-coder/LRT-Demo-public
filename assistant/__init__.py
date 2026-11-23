"""
Lab Request Assistant: the integrated agent pipeline.

  coordinator (intake)  ->  requirements (retrieval + equipment)  ->  planner (ToT)  <->  reviewer (code checks + critic)
                        ->  coordinator (draft writer)  ->  engineer review in the GUI (nothing is submitted)

Entry points: assistant.graph.run(request, ...) and `python -m assistant.run --request "..."`.
"""
