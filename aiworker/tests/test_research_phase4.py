import unittest
from aiworker.research.controller import ResearchController
from aiworker.research.models import ResearchGoal
from aiworker.research.search import SearchEngine
from aiworker.research.scraper import ScraperEngine


class TestResearchDeterminism(unittest.TestCase):

    def test_same_goal_produces_identical_report(self):
        controller = ResearchController(
            search_engine=SearchEngine(),
            scraper_engine=ScraperEngine(),
        )

        goal = ResearchGoal(
         topic="linux file permissions",
         depth=1,
          max_sources=50,
        )

        report1 = controller.run(goal)
        report2 = controller.run(goal)

        self.assertEqual(report1, report2)


if __name__ == "__main__":
    unittest.main()
