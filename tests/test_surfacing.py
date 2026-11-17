import sys
import os
import json
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from boardcam.surface import _get_tool


class TestSurfacing(unittest.TestCase):
    def setUp(self):
        tools_file = os.path.join(os.path.dirname(__file__), "..", "data", "tools.json")
        with open(tools_file, 'r') as f:
            self.tools = json.load(f)

    def test_tools_json_has_surfacing(self):
        surface_tools = [tool for tool in self.tools if "surface" in tool.get("roles", [])]
        self.assertEqual(len(surface_tools), 1)
        tool = surface_tools[0]
        self.assertEqual(tool["id"], "surfacing_35")
        self.assertEqual(tool["dia"], 34.9)
        self.assertEqual(tool["shank"], 6.35)

    def test_get_tool_default_is_surface(self):
        result = _get_tool(self.tools, None)
        self.assertEqual(result["id"], "surfacing_35")

    def test_get_tool_by_id(self):
        result = _get_tool(self.tools, "surfacing_35")
        self.assertEqual(result["dia"], 34.9)


if __name__ == "__main__":
    unittest.main()
