from aiworker.llm.ollama_backend import OllamaBackend

prompt = """GOAL:
Fix planner to use LLM for tool selection instead of default list_files.

TASK:
Modify task_agent.py:

1. Use:
   ModelRouter + OllamaBackend("llama3:8b")

2. Replace:
   tool = "list_files"

3. With:
   llm_response = router.generate(ModelRole.PLANNER, prompt)

4. Prompt:
   "User task: {task}
    Tools: system_info, list_files, read_file
    Return only tool name"

5. Add mapping:
   system → system_info
   list → list_files
   read → read_file

6. Add logging

RETURN:
Updated code only."""

model = OllamaBackend("llama3:8b")

response = model.generate(prompt)

print(response)
