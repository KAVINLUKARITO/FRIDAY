from aiworker.autonomy.controller import EvolutionController

controller = EvolutionController()

controller.run(
    goal="""
Improve workspace/game_target.py

Task:
Modify solve(n: int) to correctly return sum of integers from 1 to n.

Constraints:
- Deterministic
- No external imports
- Pure Python
- No modifying other files
- Keep under 15 lines
- Do not change function signature

Expected:
solve(5) == 15
solve(10) == 55
"""
)
