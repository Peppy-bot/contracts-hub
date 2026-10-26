"""Tests of check_marks.py, on repositories that each test writes in a temporary directory."""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest


SCRIPT = Path(__file__).with_name("check_marks.py")
SPEC = importlib.util.spec_from_file_location("check_marks", SCRIPT)
check_marks = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check_marks
SPEC.loader.exec_module(check_marks)


MARK_LIST = """
// The marks of the test repository.
{
  marks: [
    { name: "moves_robot", owner: "peppy", meaning: "The member moves the robot." },
    { name: "item_id", owner: "workflow", meaning: "The field holds an item id." },
  ],
}
"""

ARM = """
// An arm.
{
  peppy_schema: "contract/v1",
  manifest: { name: "arm", tag: "v1" },
  interfaces: {
    topics: [
      { name: "state", qos_profile: "sensor_data", message_format: { x: "f64" } },
    ],
    services: [
      {
        name: "stop",
        request_message_format: { reason: "string" },
      },
    ],
    actions: [
      {
        name: "move",
        goal_service: {
          request_message_format: {
            item_id: { $type: "string", $marks: ["item_id"] },
          },
        },
        result_service: { response_message_format: { done: "bool" } },
        marks: ["moves_robot"],
      },
    ],
  },
}
"""


def mark_entry(name="moves_robot", owner="peppy", meaning="The member moves the robot."):
    return {"name": name, "owner": owner, "meaning": meaning}


def contract(interfaces):
    return {
        "peppy_schema": "contract/v1",
        "manifest": {"name": "arm", "tag": "v1"},
        "interfaces": interfaces,
    }


class RepositoryTestCase(unittest.TestCase):
    """A test that writes a repository in a temporary directory."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(textwrap.dedent(text), encoding="utf-8")

    def write_repository(self, contracts):
        self.write("marks.json5", MARK_LIST)
        for path, text in contracts.items():
            self.write(path, text)

    def run_main(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = check_marks.main(["--root", str(self.root)])
        return status, stdout.getvalue(), stderr.getvalue()


class MarkNameTest(unittest.TestCase):
    def test_a_name_is_words_of_lowercase_letters_and_digits(self):
        for name in ["moves_robot", "item_id", "x", "pose2d", "a" * 64]:
            self.assertIsNone(check_marks.mark_name_problem(name), name)

    def test_a_name_that_breaks_the_rule_gives_its_reason(self):
        cases = {
            "": "empty",
            "a" * 65: "longer than 64 bytes",
            "Moves": "only lowercase ASCII letters",
            "a-b": "only lowercase ASCII letters",
            "é": "only lowercase ASCII letters",
            "moves__robot": "words that each start",
            "_moves": "words that each start",
            "moves_": "words that each start",
            "2d": "words that each start",
            "a_2": "words that each start",
        }
        for name, reason in cases.items():
            self.assertIn(reason, check_marks.mark_name_problem(name), name)


class ParseMarkListTest(unittest.TestCase):
    def assert_refused(self, document, *expected):
        with self.assertRaises(check_marks.MarkListError) as caught:
            check_marks.parse_mark_list(document)
        self.assertEqual(len(caught.exception.problems), len(expected), caught.exception.problems)
        for problem, text in zip(caught.exception.problems, expected):
            self.assertIn(text, problem)

    def test_a_valid_list_gives_each_mark_by_name(self):
        marks = check_marks.parse_mark_list(
            {"marks": [mark_entry(), mark_entry("item_id", "workflow", "An item id.")]}
        )
        self.assertEqual(list(marks), ["moves_robot", "item_id"])
        self.assertEqual(
            marks["item_id"],
            check_marks.MarkDefinition(name="item_id", owner="workflow", meaning="An item id."),
        )

    def test_an_empty_list_names_no_mark(self):
        self.assertEqual(check_marks.parse_mark_list({"marks": []}), {})

    def test_the_document_is_an_object_with_the_one_key_marks(self):
        for document in [[], "marks", {}, {"marks": [], "owners": []}]:
            self.assert_refused(document, "the one key `marks`")
        self.assert_refused({"marks": {"moves_robot": "peppy"}}, "`marks` is not a list")

    def test_each_entry_is_an_object_with_a_name_an_owner_and_a_meaning(self):
        self.assert_refused({"marks": ["moves_robot"]}, "entry 1 of `marks` is not an object")
        self.assert_refused(
            {"marks": [{"name": "moves_robot"}]},
            "entry 1 of `marks` has no `owner`",
            "entry 1 of `marks` has no `meaning`",
        )
        self.assert_refused(
            {"marks": [dict(mark_entry(), owners="peppy")]},
            'entry 1 of `marks` has the unknown key "owners"',
        )

    def test_a_name_that_breaks_the_rule_is_refused(self):
        self.assert_refused(
            {"marks": [mark_entry(), mark_entry(name="Moves_Robot")]},
            'entry 2 of `marks`: "Moves_Robot" is not a mark name: it may hold only',
        )
        self.assert_refused({"marks": [mark_entry(name=7)]}, "`name` is not a string")

    def test_a_name_listed_twice_is_refused(self):
        self.assert_refused(
            {"marks": [mark_entry(), mark_entry(owner="workflow")]},
            'entry 2 of `marks`: mark "moves_robot" is in the list twice',
        )

    def test_an_empty_owner_or_meaning_is_refused(self):
        self.assert_refused(
            {"marks": [mark_entry(owner=""), mark_entry(name="item_id", meaning="  ")]},
            "entry 1 of `marks`: `owner` is not a non-empty string",
            "entry 2 of `marks`: `meaning` is not a non-empty string",
        )
        self.assert_refused({"marks": [mark_entry(owner=None)]}, "`owner` is not a non-empty string")


class ContractMarkSitesTest(unittest.TestCase):
    def sites(self, interfaces):
        return [
            (site.member_kind, site.member_name, site.field, site.marks)
            for site in check_marks.contract_mark_sites(contract(interfaces), "robot/arm.json5")
        ]

    def test_each_kind_of_member_gives_its_marks(self):
        sites = self.sites(
            {
                "topics": [{"name": "state", "marks": ["robot_state"]}],
                "services": [{"name": "stop"}, {"name": "home", "marks": ["moves_robot"]}],
                "actions": [{"name": "move", "marks": ["moves_robot", "long_motion"]}],
            }
        )
        self.assertEqual(
            sites,
            [
                ("topic", "state", None, ["robot_state"]),
                ("service", "home", None, ["moves_robot"]),
                ("action", "move", None, ["moves_robot", "long_motion"]),
            ],
        )

    def test_field_marks_are_found_through_objects_arrays_and_items(self):
        sites = self.sites(
            {
                "services": [
                    {
                        "name": "check",
                        "request_message_format": {
                            "item_id": {"$type": "string", "$marks": ["item_id"]},
                            "plain": "f64",
                        },
                        "response_message_format": {
                            "results": {
                                "$type": "array",
                                "$marks": ["result_list"],
                                "$items": {
                                    "$type": "object",
                                    "$marks": ["result"],
                                    "arm": {"$type": "string", "$marks": ["arm_name"]},
                                    "corners": {
                                        "$type": "array",
                                        "$items": {"$type": "f64", "$marks": ["corner"]},
                                    },
                                },
                            },
                            "placement": {
                                "$type": "object",
                                "position": {
                                    "$type": "array",
                                    "$items": "f64",
                                    "$marks": ["location"],
                                },
                            },
                        },
                    }
                ]
            }
        )
        self.assertEqual(
            sites,
            [
                ("service", "check", "request_message_format.item_id", ["item_id"]),
                ("service", "check", "response_message_format.results", ["result_list"]),
                ("service", "check", "response_message_format.results[]", ["result"]),
                ("service", "check", "response_message_format.results[].arm", ["arm_name"]),
                ("service", "check", "response_message_format.results[].corners[]", ["corner"]),
                (
                    "service",
                    "check",
                    "response_message_format.placement.position",
                    ["location"],
                ),
            ],
        )

    def test_every_message_format_of_a_member_is_read(self):
        def marked(mark):
            return {"value": {"$type": "string", "$marks": [mark]}}

        sites = self.sites(
            {
                "topics": [{"name": "state", "message_format": marked("topic_field")}],
                "actions": [
                    {
                        "name": "move",
                        "goal_service": {
                            "request_message_format": marked("goal_request"),
                            "response_message_format": marked("goal_response"),
                        },
                        "feedback_topic": {"message_format": marked("feedback")},
                        "result_service": {"response_message_format": marked("result")},
                    }
                ],
            }
        )
        self.assertEqual(
            [(kind, field, marks) for kind, _, field, marks in sites],
            [
                ("topic", "message_format.value", ["topic_field"]),
                ("action", "goal_service.request_message_format.value", ["goal_request"]),
                ("action", "goal_service.response_message_format.value", ["goal_response"]),
                ("action", "feedback_topic.message_format.value", ["feedback"]),
                ("action", "result_service.response_message_format.value", ["result"]),
            ],
        )

    def test_a_member_without_a_name_is_named_by_its_position(self):
        self.assertEqual(
            self.sites({"services": [{"name": "a"}, {"marks": ["moves_robot"]}]}),
            [("service", "#2", None, ["moves_robot"])],
        )

    def test_a_document_without_interfaces_gives_no_mark(self):
        self.assertEqual(
            check_marks.contract_mark_sites({"peppy_schema": "contract/v1"}, "robot/arm.json5"),
            [],
        )


class CheckRepositoryTest(RepositoryTestCase):
    def test_a_repository_whose_marks_are_all_listed_passes(self):
        self.write_repository({"robot/arm.json5": ARM})
        result = check_marks.check_repository(self.root)
        self.assertEqual(result.problems, [])
        self.assertEqual((result.contracts, result.marks, result.listed_marks), (1, 2, 2))

    def test_a_member_mark_that_the_list_does_not_name_is_refused(self):
        self.write_repository(
            {"robot/arm.json5": ARM.replace('marks: ["moves_robot"]', 'marks: ["moves_robt"]')}
        )
        self.assertEqual(
            check_marks.check_repository(self.root).problems,
            [
                'robot/arm.json5: action move: mark "moves_robt" is not in the mark list '
                "(marks.json5)"
            ],
        )

    def test_a_field_mark_that_the_list_does_not_name_is_refused(self):
        self.write_repository(
            {"robot/arm.json5": ARM.replace('$marks: ["item_id"]', '$marks: ["item_id", "itme_id"]')}
        )
        self.assertEqual(
            check_marks.check_repository(self.root).problems,
            [
                "robot/arm.json5: action move, field goal_service.request_message_format.item_id: "
                'mark "itme_id" is not in the mark list (marks.json5)'
            ],
        )

    def test_each_unnamed_mark_of_each_contract_gives_one_line_in_path_order(self):
        unnamed = ARM.replace('["moves_robot"]', '["moves_robot", "a", "b"]')
        self.write_repository({"z/arm.json5": unnamed, "a/arm.json5": unnamed})
        problems = check_marks.check_repository(self.root).problems
        self.assertEqual(
            [problem.split(":")[0] + " " + problem.split('"')[1] for problem in problems],
            ["a/arm.json5 a", "a/arm.json5 b", "z/arm.json5 a", "z/arm.json5 b"],
        )

    def test_marks_that_are_not_a_list_of_names_are_refused(self):
        self.write_repository(
            {
                "robot/arm.json5": ARM.replace('marks: ["moves_robot"]', 'marks: "moves_robot"'),
                "robot/hand.json5": ARM.replace('$marks: ["item_id"]', "$marks: [1]"),
            }
        )
        self.assertEqual(
            check_marks.check_repository(self.root).problems,
            [
                "robot/arm.json5: action move: the marks are not a list of mark names",
                "robot/hand.json5: action move, field goal_service.request_message_format.item_id: "
                "the marks are not a list of mark names",
            ],
        )

    def test_documents_that_are_not_contracts_are_not_checked(self):
        self.write_repository(
            {
                "robot/arm.json5": ARM,
                "nodes/arm_node.json5": ARM.replace("contract/v1", "node/v1").replace(
                    '["moves_robot"]', '["unlisted"]'
                ),
                "notes.json5": '{ marks: ["unlisted"] }',
            }
        )
        result = check_marks.check_repository(self.root)
        self.assertEqual(result.problems, [])
        self.assertEqual(result.contracts, 1)

    def test_hidden_directories_and_files_are_not_checked(self):
        unlisted = ARM.replace('["moves_robot"]', '["unlisted"]')
        self.write_repository(
            {
                "robot/arm.json5": ARM,
                ".github/fixtures/arm.json5": unlisted,
                "robot/.draft.json5": unlisted,
            }
        )
        result = check_marks.check_repository(self.root)
        self.assertEqual(result.problems, [])
        self.assertEqual(result.contracts, 1)

    def test_a_json5_file_that_cannot_be_read_is_refused(self):
        self.write_repository(
            {
                "robot/arm.json5": ARM,
                "robot/broken.json5": "{ peppy_schema: ",
                "robot/twice.json5": ARM.replace(
                    'peppy_schema: "contract/v1",', 'peppy_schema: "contract/v1", marks: [], marks: [],'
                ),
            }
        )
        problems = check_marks.check_repository(self.root).problems
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(problems[0].startswith("robot/broken.json5: cannot read it: "), problems)
        self.assertTrue(problems[1].startswith("robot/twice.json5: cannot read it: "), problems)

    def test_a_missing_mark_list_is_refused(self):
        self.write("robot/arm.json5", ARM)
        problems = check_marks.check_repository(self.root).problems
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith("marks.json5: cannot read it: "), problems)

    def test_a_malformed_mark_list_gives_its_problems_alone(self):
        self.write("marks.json5", '{ marks: [{ name: "Moves", owner: "", meaning: "x" }] }')
        self.write("robot/arm.json5", ARM)
        self.assertEqual(
            check_marks.check_repository(self.root).problems,
            [
                'marks.json5: entry 1 of `marks`: "Moves" is not a mark name: it may hold only '
                "lowercase ASCII letters, digits and `_`",
                "marks.json5: entry 1 of `marks`: `owner` is not a non-empty string",
            ],
        )

    def test_a_repository_without_contracts_is_refused(self):
        self.write_repository({})
        problems = check_marks.check_repository(self.root).problems
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("found no contract document (contract/v1)", problems[0])


class MainTest(RepositoryTestCase):
    def test_a_passing_check_exits_0_with_a_summary(self):
        self.write_repository({"robot/arm.json5": ARM})
        status, stdout, stderr = self.run_main()
        self.assertEqual(status, 0)
        self.assertEqual(
            stdout,
            "Each mark of the contracts is in marks.json5 "
            "(contracts: 1, marks given: 2, marks in the list: 2).\n",
        )
        self.assertEqual(stderr, "")

    def test_a_failing_check_exits_1_with_one_line_per_problem(self):
        self.write_repository(
            {"robot/arm.json5": ARM.replace('["moves_robot"]', '["moves_robot", "a", "b"]')}
        )
        status, stdout, stderr = self.run_main()
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(
            stderr.splitlines(),
            [
                'robot/arm.json5: action move: mark "a" is not in the mark list (marks.json5)',
                'robot/arm.json5: action move: mark "b" is not in the mark list (marks.json5)',
            ],
        )


if __name__ == "__main__":
    unittest.main()
