"""Tests for gla.eval.llm_agent."""

import json
import unittest
from unittest.mock import MagicMock, patch

from gla.eval.llm_agent import (
    AgentResult,
    CODE_ONLY_TOOLS,
    EvalAgent,
    GLA_TOOLS,
    GlaToolExecutor,
)


# ---------------------------------------------------------------------------
# Tool definition structure
# ---------------------------------------------------------------------------

class TestGlaToolsStructure(unittest.TestCase):
    def test_all_tools_have_required_keys(self):
        for tool in GLA_TOOLS:
            self.assertIn("name", tool, f"Tool missing 'name': {tool}")
            self.assertIn("description", tool, f"Tool {tool['name']} missing 'description'")
            self.assertIn("input_schema", tool, f"Tool {tool['name']} missing 'input_schema'")

    def test_tool_names(self):
        names = {t["name"] for t in GLA_TOOLS}
        expected = {
            "query_frame",
            "inspect_drawcall",
            "query_pixel",
            "query_scene",
            "compare_frames",
            "read_source_file",
        }
        self.assertEqual(names, expected)

    def test_input_schemas_are_objects(self):
        for tool in GLA_TOOLS:
            schema = tool["input_schema"]
            self.assertEqual(schema["type"], "object")
            self.assertIn("properties", schema)

    def test_required_fields_present_in_schemas(self):
        for tool in GLA_TOOLS:
            self.assertIn("required", tool["input_schema"],
                          f"Tool {tool['name']} schema missing 'required'")


class TestCodeOnlyTools(unittest.TestCase):
    def test_code_only_tools_has_one_entry(self):
        self.assertEqual(len(CODE_ONLY_TOOLS), 1)

    def test_code_only_tools_is_read_source_file(self):
        self.assertEqual(CODE_ONLY_TOOLS[0]["name"], "read_source_file")

    def test_code_only_tools_is_last_gla_tool(self):
        self.assertIs(CODE_ONLY_TOOLS[0], GLA_TOOLS[-1])


# ---------------------------------------------------------------------------
# GlaToolExecutor HTTP routing
# ---------------------------------------------------------------------------

class TestGlaToolExecutorQueryFrame(unittest.TestCase):
    def setUp(self):
        self.executor = GlaToolExecutor(
            base_url="http://localhost:8080",
            token="test-token",
            frame_id=42,
        )

    @patch("gla.eval.llm_agent.requests.get")
    def test_query_frame_overview_url(self, mock_get):
        mock_get.return_value = MagicMock(text='{"frame_id": 42}')
        self.executor._query_frame({"query_type": "overview"})
        mock_get.assert_called_once_with(
            "http://localhost:8080/api/v1/frames/42/overview",
            headers={"Authorization": "Bearer test-token"},
        )

    @patch("gla.eval.llm_agent.requests.get")
    def test_query_frame_drawcalls_url(self, mock_get):
        mock_get.return_value = MagicMock(text='{"items": []}')
        self.executor._query_frame({"query_type": "drawcalls", "limit": 10, "offset": 5})
        mock_get.assert_called_once_with(
            "http://localhost:8080/api/v1/frames/42/drawcalls",
            params={"limit": 10, "offset": 5},
            headers={"Authorization": "Bearer test-token"},
        )

    @patch("gla.eval.llm_agent.requests.get")
    def test_query_frame_unknown_type_returns_error(self, mock_get):
        result = self.executor._query_frame({"query_type": "unknown"})
        mock_get.assert_not_called()
        data = json.loads(result)
        self.assertIn("error", data)

    @patch("gla.eval.llm_agent.requests.get")
    def test_query_frame_drawcalls_default_pagination(self, mock_get):
        mock_get.return_value = MagicMock(text='{"items": []}')
        self.executor._query_frame({"query_type": "drawcalls"})
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["limit"], 50)
        self.assertEqual(kwargs["params"]["offset"], 0)


class TestGlaToolExecutorInspectDrawcall(unittest.TestCase):
    def setUp(self):
        self.executor = GlaToolExecutor(
            base_url="http://localhost:8080",
            token="tok",
            frame_id=1,
        )

    @patch("gla.eval.llm_agent.requests.get")
    def test_inspect_drawcall_url(self, mock_get):
        mock_get.return_value = MagicMock(text='{}')
        self.executor._inspect_drawcall({"drawcall_id": 7})
        mock_get.assert_called_once_with(
            "http://localhost:8080/api/v1/frames/1/drawcalls/7",
            headers={"Authorization": "Bearer tok"},
        )


class TestGlaToolExecutorQueryPixel(unittest.TestCase):
    def setUp(self):
        self.executor = GlaToolExecutor(
            base_url="http://localhost:8080",
            token="tok",
            frame_id=3,
        )

    @patch("gla.eval.llm_agent.requests.get")
    def test_query_pixel_uses_path_params(self, mock_get):
        mock_get.return_value = MagicMock(text='{"r":255}')
        self.executor._query_pixel({"x": 100, "y": 200})
        mock_get.assert_called_once_with(
            "http://localhost:8080/api/v1/frames/3/pixel/100/200",
            headers={"Authorization": "Bearer tok"},
        )


class TestGlaToolExecutorQueryScene(unittest.TestCase):
    def setUp(self):
        self.executor = GlaToolExecutor(
            base_url="http://localhost:8080",
            token="tok",
            frame_id=5,
        )

    @patch("gla.eval.llm_agent.requests.get")
    def test_query_scene_camera(self, mock_get):
        mock_get.return_value = MagicMock(text='{}')
        self.executor._query_scene({"query_type": "camera"})
        mock_get.assert_called_once_with(
            "http://localhost:8080/api/v1/frames/5/scene/camera",
            headers={"Authorization": "Bearer tok"},
        )

    @patch("gla.eval.llm_agent.requests.get")
    def test_query_scene_objects(self, mock_get):
        mock_get.return_value = MagicMock(text='{}')
        self.executor._query_scene({"query_type": "objects"})
        mock_get.assert_called_once_with(
            "http://localhost:8080/api/v1/frames/5/scene/objects",
            headers={"Authorization": "Bearer tok"},
        )

    @patch("gla.eval.llm_agent.requests.get")
    def test_query_scene_full_falls_through_to_scene(self, mock_get):
        mock_get.return_value = MagicMock(text='{}')
        self.executor._query_scene({"query_type": "full"})
        mock_get.assert_called_once_with(
            "http://localhost:8080/api/v1/frames/5/scene",
            headers={"Authorization": "Bearer tok"},
        )


class TestGlaToolExecutorCompareFrames(unittest.TestCase):
    def setUp(self):
        self.executor = GlaToolExecutor(
            base_url="http://localhost:8080",
            token="tok",
            frame_id=1,
        )

    @patch("gla.eval.llm_agent.requests.get")
    def test_compare_frames_url_and_params(self, mock_get):
        mock_get.return_value = MagicMock(text='{}')
        self.executor._compare_frames({"frame_id_a": 10, "frame_id_b": 20, "depth": "drawcalls"})
        mock_get.assert_called_once_with(
            "http://localhost:8080/api/v1/diff/10/20",
            params={"depth": "drawcalls"},
            headers={"Authorization": "Bearer tok"},
        )

    @patch("gla.eval.llm_agent.requests.get")
    def test_compare_frames_default_depth(self, mock_get):
        mock_get.return_value = MagicMock(text='{}')
        self.executor._compare_frames({"frame_id_a": 1, "frame_id_b": 2})
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["depth"], "summary")


class TestGlaToolExecutorExecuteDispatch(unittest.TestCase):
    def setUp(self):
        self.executor = GlaToolExecutor(
            base_url="http://localhost:8080",
            token="tok",
            frame_id=1,
        )

    def test_execute_unknown_tool_returns_error_json(self):
        result = self.executor.execute("nonexistent_tool", {})
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("nonexistent_tool", data["error"])


# ---------------------------------------------------------------------------
# EvalAgent system prompt and user message
# ---------------------------------------------------------------------------

class TestEvalAgentSystemPrompt(unittest.TestCase):
    def setUp(self):
        with patch("gla.eval.llm_agent.Anthropic"):
            self.agent = EvalAgent(api_key="fake-key")

    def test_with_gla_prompt_mentions_tools(self):
        prompt = self.agent._build_system_prompt("with_gla")
        for tool in ["query_frame", "inspect_drawcall", "query_pixel",
                     "query_scene", "compare_frames", "read_source_file"]:
            self.assertIn(tool, prompt, f"'{tool}' not mentioned in with_gla prompt")

    def test_with_gla_prompt_ends_with_diagnosis_fix(self):
        prompt = self.agent._build_system_prompt("with_gla")
        self.assertIn("DIAGNOSIS:", prompt)
        self.assertIn("FIX:", prompt)

    def test_code_only_prompt_does_not_mention_gla_tools(self):
        prompt = self.agent._build_system_prompt("code_only")
        for tool in ["query_frame", "inspect_drawcall", "query_pixel",
                     "query_scene", "compare_frames"]:
            self.assertNotIn(tool, prompt, f"GLA tool '{tool}' should not appear in code_only prompt")

    def test_code_only_prompt_mentions_read_source_file(self):
        prompt = self.agent._build_system_prompt("code_only")
        self.assertIn("read_source_file", prompt)

    def test_code_only_prompt_ends_with_diagnosis_fix(self):
        prompt = self.agent._build_system_prompt("code_only")
        self.assertIn("DIAGNOSIS:", prompt)
        self.assertIn("FIX:", prompt)

    def test_unknown_mode_returns_code_only_style(self):
        # Any mode other than 'with_gla' falls into the else branch
        prompt = self.agent._build_system_prompt("other")
        self.assertIn("DIAGNOSIS:", prompt)


class TestEvalAgentUserMessage(unittest.TestCase):
    def setUp(self):
        with patch("gla.eval.llm_agent.Anthropic"):
            self.agent = EvalAgent(api_key="fake-key")

    def test_user_message_contains_scenario_description(self):
        msg = self.agent._build_user_message(
            scenario_description="The cube is rendered black instead of red.",
            source_path="/app/main.c",
        )
        self.assertIn("The cube is rendered black instead of red.", msg)

    def test_user_message_contains_source_path(self):
        msg = self.agent._build_user_message(
            scenario_description="Some bug.",
            source_path="/path/to/shader_app.cpp",
        )
        self.assertIn("/path/to/shader_app.cpp", msg)

    def test_user_message_asks_for_diagnosis_and_fix(self):
        msg = self.agent._build_user_message("desc", "/src/app.cpp")
        self.assertIn("DIAGNOSIS", msg)
        self.assertIn("FIX", msg)


# ---------------------------------------------------------------------------
# EvalAgent._run (mocked Anthropic client)
# ---------------------------------------------------------------------------

def _make_text_block(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.model_dump.return_value = {"type": "text", "text": text}
    return block


def _make_tool_use_block(tool_id: str, name: str, input_data: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = input_data
    block.model_dump.return_value = {
        "type": "tool_use", "id": tool_id, "name": name, "input": input_data
    }
    return block


def _make_response(content, stop_reason="end_turn", input_tokens=10, output_tokens=20):
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    return resp


class TestEvalAgentRunCodeOnly(unittest.TestCase):
    def setUp(self):
        with patch("gla.eval.llm_agent.Anthropic") as MockAnthropic:
            self.mock_client = MagicMock()
            MockAnthropic.return_value = self.mock_client
            self.agent = EvalAgent(api_key="fake-key", max_turns=5)

    def test_code_only_no_tool_calls_returns_result(self):
        text_block = _make_text_block(
            "DIAGNOSIS: Wrong color uniform.\nFIX: Set uColor to vec4(1,0,0,1)."
        )
        self.mock_client.messages.create.return_value = _make_response(
            [text_block], stop_reason="end_turn", input_tokens=50, output_tokens=30
        )

        result = self.agent.run_code_only(
            scenario_description="Cube is black.",
            source_code="void main() {}",
            source_path="/app/main.glsl",
        )

        self.assertIsInstance(result, AgentResult)
        self.assertIn("DIAGNOSIS", result.diagnosis)
        self.assertEqual(result.tool_calls, 0)
        self.assertEqual(result.num_turns, 1)
        self.assertEqual(result.input_tokens, 50)
        self.assertEqual(result.output_tokens, 30)
        self.assertEqual(result.total_tokens, 80)

    def test_code_only_read_source_file_tool_use(self):
        tool_block = _make_tool_use_block("tu1", "read_source_file", {"file_path": "/app/main.c"})
        text_block = _make_text_block("DIAGNOSIS: Bug.\nFIX: Fix it.")

        # Capture snapshots of the messages list at each call because mock stores
        # a reference to the same mutable list object.
        captured_messages = []

        responses = [
            _make_response([tool_block], stop_reason="tool_use", input_tokens=20, output_tokens=10),
            _make_response([text_block], stop_reason="end_turn", input_tokens=30, output_tokens=15),
        ]
        resp_iter = iter(responses)

        def side_effect(*args, **kwargs):
            captured_messages.append(list(kwargs["messages"]))
            return next(resp_iter)

        self.mock_client.messages.create.side_effect = side_effect

        result = self.agent.run_code_only(
            scenario_description="Something wrong.",
            source_code="int main() { return 0; }",
            source_path="/app/main.c",
        )

        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(result.num_turns, 2)

        # The second call should receive [user_init, assistant_turn1, user_tool_results]
        second_call_messages = captured_messages[1]
        self.assertEqual(len(second_call_messages), 3)
        tool_result_msg = second_call_messages[-1]
        self.assertEqual(tool_result_msg["role"], "user")
        self.assertEqual(tool_result_msg["content"][0]["content"], "int main() { return 0; }")


class TestEvalAgentRunWithGla(unittest.TestCase):
    def setUp(self):
        with patch("gla.eval.llm_agent.Anthropic") as MockAnthropic:
            self.mock_client = MagicMock()
            MockAnthropic.return_value = self.mock_client
            self.agent = EvalAgent(api_key="fake-key", max_turns=5)

    def test_with_gla_uses_gla_tools_list(self):
        text_block = _make_text_block("DIAGNOSIS: Bad depth test.\nFIX: Enable depth test.")
        self.mock_client.messages.create.return_value = _make_response(
            [text_block], stop_reason="end_turn"
        )

        executor = MagicMock(spec=GlaToolExecutor)
        self.agent.run_with_gla(
            scenario_description="Depth issue.",
            source_code="",
            source_path="/app/main.cpp",
            tool_executor=executor,
        )

        call_kwargs = self.mock_client.messages.create.call_args[1]
        tool_names = {t["name"] for t in call_kwargs["tools"]}
        self.assertIn("query_frame", tool_names)
        self.assertIn("inspect_drawcall", tool_names)
        self.assertIn("query_pixel", tool_names)

    def test_with_gla_delegates_tool_calls_to_executor(self):
        tool_block = _make_tool_use_block("tu2", "query_frame", {"query_type": "overview"})
        text_block = _make_text_block("DIAGNOSIS: OK.\nFIX: Nothing.")

        self.mock_client.messages.create.side_effect = [
            _make_response([tool_block], stop_reason="tool_use"),
            _make_response([text_block], stop_reason="end_turn"),
        ]

        executor = MagicMock(spec=GlaToolExecutor)
        executor.execute.return_value = '{"frame_id": 1}'

        self.agent.run_with_gla(
            scenario_description="Bug.",
            source_code="code",
            source_path="/app/main.cpp",
            tool_executor=executor,
        )

        executor.execute.assert_called_once_with("query_frame", {"query_type": "overview"})
        self.assertEqual(executor.execute.call_count, 1)


class TestEvalAgentTokenAccumulation(unittest.TestCase):
    def test_tokens_accumulate_across_turns(self):
        with patch("gla.eval.llm_agent.Anthropic") as MockAnthropic:
            mock_client = MagicMock()
            MockAnthropic.return_value = mock_client
            agent = EvalAgent(api_key="fake-key", max_turns=10)

        tool_block = _make_tool_use_block("tu3", "read_source_file", {"file_path": "/f"})
        text_block = _make_text_block("DIAGNOSIS: x.\nFIX: y.")

        mock_client.messages.create.side_effect = [
            _make_response([tool_block], stop_reason="tool_use", input_tokens=100, output_tokens=50),
            _make_response([text_block], stop_reason="end_turn", input_tokens=200, output_tokens=80),
        ]

        result = agent.run_code_only("desc", "code", "/f")

        self.assertEqual(result.input_tokens, 300)
        self.assertEqual(result.output_tokens, 130)
        self.assertEqual(result.total_tokens, 430)


class TestEvalAgentMaxTurns(unittest.TestCase):
    def test_stops_at_max_turns(self):
        with patch("gla.eval.llm_agent.Anthropic") as MockAnthropic:
            mock_client = MagicMock()
            MockAnthropic.return_value = mock_client
            agent = EvalAgent(api_key="fake-key", max_turns=3)

        tool_block = _make_tool_use_block("tu4", "read_source_file", {"file_path": "/f"})
        # Always return tool_use so the loop would run forever without the cap
        mock_client.messages.create.return_value = _make_response(
            [tool_block], stop_reason="tool_use", input_tokens=10, output_tokens=5
        )

        result = agent.run_code_only("desc", "code", "/f")
        self.assertEqual(result.num_turns, 3)


if __name__ == "__main__":
    unittest.main()
