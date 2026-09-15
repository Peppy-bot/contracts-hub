"""Deterministic contract review tests; GitHub and Claude never run live."""

from __future__ import annotations

import copy
from html import unescape
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit


SCRIPT = Path(__file__).with_name("contract_similarity.py")
SPEC = importlib.util.spec_from_file_location("contract_similarity", SCRIPT)
similarity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = similarity
SPEC.loader.exec_module(similarity)


ARM = "robot/arm.json5"
GRIPPER = "robot/gripper.json5"
NEW = "unindexed/position.json5"


def contract_text(name="arm", tag="v1", comment="Position is in meters."):
    return f"""// {comment}
{{
  peppy_schema: 'contract/v1',
  manifest: {{name: '{name}', tag: '{tag}',}},
  interfaces: {{
    actions: [{{
      name: 'move',
      goal_service: {{request_message_format: {{
        // Target in the world frame.
        position: {{$type: 'array', $items: 'f64', $length: 3}},
      }}}},
      result_service: {{response_message_format: {{success: 'bool'}}}},
    }}],
  }},
}}
"""


def contract(path, name="arm", tag="v1"):
    return {
        "id": path,
        "path": path,
        "name": name,
        "tag": tag,
        "text": contract_text(name, tag),
    }


def prepared_state():
    return {
        "status": "ready",
        "repository": "Peppy-bot/contracts-hub",
        "pr_number": 42,
        "author": "original-author",
        "head_sha": "a" * 40,
        "head_ref": "proposal",
        "base_sha": "b" * 40,
        "event_base_sha": "c" * 40,
        "base_ref": "main",
        "candidates": [contract(NEW, "position")],
        "corpus": [contract(ARM), contract(GRIPPER, "gripper")],
    }


def finding(candidate_id=NEW, contract_id=ARM):
    return {
        "candidate_id": candidate_id,
        "matches": [
            {
                "contract_id": contract_id,
                "similarities": ["Both command a Cartesian target."],
                "differences": ["The arm contract also plans joint motion."],
            }
        ],
    }


def clean_analysis(prepared):
    return {
        "status": "complete",
        "results": [
            {"candidate_id": item["id"], "matches": []}
            for item in prepared["candidates"]
        ],
    }


def pull_request(prepared):
    return {
        "number": prepared["pr_number"],
        "state": "open",
        "user": {"login": prepared["author"]},
        "head": {"sha": prepared["head_sha"], "ref": prepared["head_ref"]},
        "base": {
            "sha": prepared["event_base_sha"],
            "ref": prepared["base_ref"],
            "repo": {"full_name": prepared["repository"]},
        },
    }


def github_event(prepared):
    return {
        "number": prepared["pr_number"],
        "repository": {"full_name": prepared["repository"]},
        "sender": {"login": "rerun-reviewer"},
        "pull_request": pull_request(prepared),
    }


class FakeGitHub:
    """Only the PR, target ref, and issue-comment API routes are allowed."""

    def __init__(self, prepared):
        self.pr = pull_request(prepared)
        self.base_sha = prepared["base_sha"]
        self.prefix = f"repos/{prepared['repository']}"
        self.number = prepared["pr_number"]
        self.pages = {1: []}
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        parsed = urlsplit(path)
        route = parsed.path.lstrip("/")
        if method == "GET" and route == f"{self.prefix}/pulls/{self.number}":
            return copy.deepcopy(self.pr)
        if method == "GET" and route == f"{self.prefix}/git/ref/heads/main":
            return {"object": {"sha": self.base_sha}}
        if method == "GET" and route == f"{self.prefix}/issues/{self.number}/comments":
            page = int(parse_qs(parsed.query).get("page", ["1"])[0])
            return copy.deepcopy(self.pages.get(page, []))
        if method in {"POST", "PATCH"} and route.startswith(f"{self.prefix}/issues/"):
            return {"id": 900}
        raise AssertionError(f"Unexpected GitHub route: {method} {path}")

    @property
    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]


class GitFixture:
    """Small real history with no user Git config, signing, or hooks."""

    def __init__(self, root):
        self.path = root / "repo"
        self.path.mkdir()
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(root),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
        }
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Contract Test")
        self.git("config", "user.email", "contracts@example.test")
        self.write(
            "peppy_repository.json5", "{peppy_schema: 'repository/v1', contracts: {}}"
        )
        self.commit("Initialize repository")

    def git(self, *args):
        return subprocess.run(
            [
                "git",
                "-c",
                "commit.gpgSign=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                str(self.path),
                *args,
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def write(self, path, text):
        target = self.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {
                    "PATH": os.environ["PATH"],
                    "CLAUDE_CODE_OAUTH_TOKEN": "test-only-oauth-token",
                },
                clear=True,
            )
        )
        self.warnings = self.enterContext(
            mock.patch("sys.stderr", new_callable=io.StringIO)
        )
        self.model = self.enterContext(
            mock.patch.object(
                similarity,
                "run_claude",
                side_effect=AssertionError("Unexpected model call"),
            )
        )
        self.api = self.enterContext(
            mock.patch.object(
                similarity,
                "github_api",
                side_effect=AssertionError("Unexpected GitHub call"),
            )
        )


class ParseContractTests(OfflineTestCase):
    def test_json5_source_comments_and_action_goal_are_preserved_verbatim(self):
        source = contract_text(comment="Physical coordinates, not a high-level task.")
        parsed = similarity.parse_contract(ARM, source)
        self.assertEqual(
            parsed, {"id": ARM, "path": ARM, "name": "arm", "tag": "v1", "text": source}
        )
        self.assertIn("// Target in the world frame.", parsed["text"])
        self.assertIn("request_message_format", parsed["text"])

    def test_oversized_source_is_unavailable_before_parsing(self):
        with self.assertRaises(similarity.Unavailable) as raised:
            similarity.parse_contract(ARM, "//" + "x" * similarity.MAX_BLOB_BYTES)
        self.assertEqual(raised.exception.reason, "input_limit")

    def test_non_contract_json5_is_not_a_candidate(self):
        for source in ("{peppy_schema: 'repository/v1', contracts: {}}", "{other: 1}"):
            with self.subTest(source=source):
                self.assertIsNone(similarity.parse_contract("metadata.json5", source))

    def test_invalid_json5_and_contract_identity_raise_unavailable(self):
        for source in (
            "{",
            "{peppy_schema: 'contract/v1'}",
            "{peppy_schema: 'contract/v1', manifest: {name: 7, tag: 'v1'}}",
            "{peppy_schema: 'contract/v1', manifest: {name: 'arm', tag: ''}}",
        ):
            with self.subTest(source=source):
                with self.assertRaises(similarity.Unavailable):
                    similarity.parse_contract(ARM, source)


class CollectContractsTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = GitFixture(self.root)
        self.repo.write(ARM, contract_text())
        self.repo.write(GRIPPER, contract_text("gripper"))
        self.base = self.repo.commit("Base contracts")
        self.repo.git("checkout", "-b", "proposal")

    def collect(self):
        return similarity.collect_contracts(
            self.repo.path, self.base, self.repo.git("rev-parse", "HEAD")
        )

    def test_unindexed_addition_is_collected_without_manifest_changes(self):
        self.repo.write(NEW, contract_text("position"))
        self.repo.commit("Add unindexed contract")
        result = self.collect()
        self.assertEqual([item["id"] for item in result["candidates"]], [NEW])
        self.assertEqual({item["id"] for item in result["corpus"]}, {ARM, GRIPPER})

    def test_comment_only_contract_edit_is_a_candidate(self):
        source = contract_text(
            comment="Positions are world-frame meters, not joint radians."
        )
        self.repo.write(ARM, source)
        self.repo.commit("Clarify coordinates")
        result = self.collect()
        self.assertEqual([item["id"] for item in result["candidates"]], [ARM])
        self.assertEqual(result["candidates"][0]["text"], source)

    def test_rename_reads_new_path_and_removes_old_path_from_corpus(self):
        renamed = "moved/arm.json5"
        (self.repo.path / "moved").mkdir()
        self.repo.git("mv", ARM, renamed)
        self.repo.commit("Move contract")
        result = self.collect()
        self.assertEqual([item["id"] for item in result["candidates"]], [renamed])
        self.assertEqual({item["id"] for item in result["corpus"]}, {GRIPPER})

    def test_explicit_removal_is_excluded_from_comparison(self):
        self.repo.git("rm", GRIPPER)
        self.repo.write(NEW, contract_text("position"))
        self.repo.commit("Replace gripper contract")
        result = self.collect()
        self.assertEqual([item["id"] for item in result["candidates"]], [NEW])
        self.assertEqual({item["id"] for item in result["corpus"]}, {ARM})

    def test_behind_branch_keeps_base_only_additions_and_uses_current_base_text(self):
        self.repo.write(NEW, contract_text("position"))
        head = self.repo.commit("Proposed contract")
        self.repo.git("checkout", "main")
        base_only = "robot/base_only.json5"
        self.repo.write(base_only, contract_text("base_only"))
        updated = contract_text(comment="Latest target-branch semantics.")
        self.repo.write(ARM, updated)
        base = self.repo.commit("Target branch advances")
        result = similarity.collect_contracts(self.repo.path, base, head)
        self.assertEqual([item["id"] for item in result["candidates"]], [NEW])
        corpus = {item["id"]: item for item in result["corpus"]}
        self.assertEqual(set(corpus), {ARM, GRIPPER, base_only})
        self.assertEqual(corpus[ARM]["text"], updated)

    def test_working_tree_is_not_a_source_of_proposed_contracts(self):
        committed = contract_text("position")
        self.repo.write(NEW, committed)
        self.repo.commit("Proposed contract")
        self.repo.write(NEW, "not valid JSON5")
        self.repo.write("untracked.json5", "{also: 'not committed'}")
        result = self.collect()
        self.assertEqual([item["id"] for item in result["candidates"]], [NEW])
        self.assertEqual(result["candidates"][0]["text"], committed)

    def test_documentation_and_deletion_only_changes_skip_inference(self):
        for delete_contract in (False, True):
            with self.subTest(delete_contract=delete_contract):
                self.repo.write("README.md", "Contract documentation.\n")
                if delete_contract:
                    self.repo.git("rm", GRIPPER)
                self.repo.commit("Documentation or removal")
                inventory = self.collect()
                self.assertEqual(inventory["candidates"], [])
                prepared = {**prepared_state(), **inventory, "status": "no_changes"}
                self.assertEqual(similarity.analyze(prepared)["status"], "no_changes")
        self.model.assert_not_called()

    def test_blob_total_bytes_and_inventory_count_limits_fail_without_truncation(self):
        self.repo.write(NEW, contract_text("position"))
        self.repo.write("other.json5", contract_text("other"))
        self.repo.commit("Two proposed contracts")
        for limit, value in (
            ("MAX_BLOB_BYTES", 1),
            ("MAX_INPUT_BYTES", 1),
            ("MAX_CANDIDATES", 1),
            ("MAX_CONTRACTS", 1),
            ("MAX_JSON5_FILES", 1),
        ):
            with self.subTest(limit=limit), mock.patch.object(similarity, limit, value):
                with self.assertRaises(similarity.Unavailable) as raised:
                    self.collect()
                self.assertEqual(raised.exception.reason, "input_limit")

    def test_duplicate_candidate_identities_are_unavailable(self):
        self.repo.write(NEW, contract_text("position"))
        self.repo.write("alias.json5", contract_text("position"))
        self.repo.commit("Duplicate proposed identities")
        with self.assertRaises(similarity.Unavailable) as raised:
            self.collect()
        self.assertEqual(raised.exception.reason, "invalid_contract")

    def test_duplicate_corpus_identities_are_unavailable(self):
        self.repo.git("checkout", "main")
        self.repo.write("alias.json5", contract_text("arm"))
        self.base = self.repo.commit("Duplicate target identities")
        self.repo.git("checkout", "proposal")
        self.repo.write(NEW, contract_text("position"))
        self.repo.commit("Proposed contract")
        with self.assertRaises(similarity.Unavailable) as raised:
            self.collect()
        self.assertEqual(raised.exception.reason, "invalid_contract")

    def test_invalid_proposed_json5_is_unavailable(self):
        self.repo.write(NEW, "{peppy_schema: 'contract/v1',")
        self.repo.commit("Invalid proposed contract")
        with self.assertRaises(similarity.Unavailable):
            self.collect()

    def test_invalid_unchanged_comparison_contract_is_not_silently_omitted(self):
        self.repo.git("checkout", "main")
        self.repo.write(ARM, "{malformed")
        self.base = self.repo.commit("Invalid target contract")
        self.repo.git("checkout", "proposal")
        self.repo.write(NEW, contract_text("position"))
        self.repo.commit("Proposed contract")
        with self.assertRaises(similarity.Unavailable):
            self.collect()

    def test_symlink_is_rejected_without_reading_target(self):
        (self.repo.path / "linked.json5").symlink_to(ARM)
        self.repo.commit("Symlink contract")
        with self.assertRaises(similarity.Unavailable):
            self.collect()

    def test_non_utf8_contract_is_unavailable(self):
        (self.repo.path / "invalid.json5").write_bytes(b"\xff\xfe")
        self.repo.commit("Invalid text encoding")
        with self.assertRaises(similarity.Unavailable):
            self.collect()


class StatePhaseTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.state = self.root / "state"
        self.context = prepared_state()
        self.event_path = self.root / "event.json"
        os.environ.update(
            GITHUB_REPOSITORY=self.context["repository"],
            GITHUB_EVENT_PATH=str(self.event_path),
        )

    def write_event(self):
        self.event_path.write_text(
            json.dumps(github_event(self.context)), encoding="utf-8"
        )

    def phase(self, name, *args):
        self.assertEqual(
            similarity.main([name, "--state-dir", str(self.state), *args]), 0
        )
        return json.loads((self.state / f"{name}.json").read_text(encoding="utf-8"))

    def prepare_git_history(self):
        repo = GitFixture(self.root)
        repo.write(ARM, contract_text())
        event_base = repo.commit("Event base")
        repo.git("checkout", "-b", "proposal")
        repo.write(NEW, contract_text("position"))
        head = repo.commit("Proposal")
        repo.git("checkout", "main")
        repo.write(GRIPPER, contract_text("gripper"))
        base = repo.commit("Current target")
        repo.git("update-ref", "refs/contract-similarity/head", head)
        repo.git("update-ref", "refs/contract-similarity/base", base)
        self.context.update(head_sha=head, base_sha=base, event_base_sha=event_base)
        self.write_event()
        real_git = similarity.run_git

        def git_without_network(repo_dir, *args):
            if args[0] == "fetch":
                return b""
            if args[0] not in {
                "rev-parse",
                "merge-base",
                "diff",
                "ls-tree",
                "cat-file",
            }:
                raise AssertionError(f"Unexpected Git command: {args}")
            return real_git(repo_dir, *args)

        self.git = self.enterContext(
            mock.patch.object(similarity, "run_git", side_effect=git_without_network)
        )
        return repo

    def test_prepare_uses_fetched_target_tip_preserving_event_metadata(self):
        repo = self.prepare_git_history()
        result = self.phase("prepare", "--repo-dir", str(repo.path))
        self.assertEqual(result["status"], "ready")
        for key in ("head_sha", "base_sha", "event_base_sha", "author"):
            self.assertEqual(result[key], self.context[key])
        self.assertEqual([item["id"] for item in result["candidates"]], [NEW])
        self.assertEqual({item["id"] for item in result["corpus"]}, {ARM, GRIPPER})
        fetch = self.git.call_args_list[0].args
        self.assertIn("https://github.com/Peppy-bot/contracts-hub.git", fetch)
        self.assertIn("+refs/pull/42/head:refs/contract-similarity/head", fetch)
        self.model.assert_not_called()

    def test_head_race_and_git_failure_write_unavailable_state_and_return_zero(self):
        repo = self.prepare_git_history()
        repo.git(
            "update-ref", "refs/contract-similarity/head", self.context["base_sha"]
        )
        result = self.phase("prepare", "--repo-dir", str(repo.path))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "head_changed")
        self.git.side_effect = similarity.Unavailable("git")
        result = self.phase("prepare", "--repo-dir", str(repo.path))
        self.assertEqual(result["reason"], "git")
        self.assertIn("::warning::", self.warnings.getvalue())
        self.model.assert_not_called()

    def test_invalid_prepare_preserves_current_base_for_unavailable_publication(self):
        repo = self.prepare_git_history()
        repo.git("checkout", "proposal")
        (repo.path / NEW).write_bytes(b"\xff")
        head = repo.commit("Invalid contract bytes")
        repo.git("update-ref", "refs/contract-similarity/head", head)
        self.context["head_sha"] = head
        self.write_event()
        result = self.phase("prepare", "--repo-dir", str(repo.path))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "invalid_contract")
        self.assertEqual(result["base_sha"], self.context["base_sha"])

    def test_prepare_clears_results_from_an_earlier_run(self):
        repo = self.prepare_git_history()
        self.state.mkdir()
        for phase in ("analyze", "comment"):
            (self.state / f"{phase}.json").write_text("{}", encoding="utf-8")
        self.phase("prepare", "--repo-dir", str(repo.path))
        self.assertFalse((self.state / "analyze.json").exists())
        self.assertFalse((self.state / "comment.json").exists())

    def test_missing_and_corrupt_analysis_inputs_fail_open_without_inference(self):
        for contents in (None, "{not JSON", "[]"):
            with self.subTest(contents=contents):
                self.state.mkdir(exist_ok=True)
                if contents is not None:
                    (self.state / "prepare.json").write_text(contents, encoding="utf-8")
                result = self.phase("analyze")
                self.assertEqual(
                    result, {"status": "unavailable", "reason": "missing_state"}
                )
        self.model.assert_not_called()

    def test_missing_state_publisher_uses_event_author_and_reports_unavailable(self):
        self.context["base_sha"] = self.context["event_base_sha"]
        self.write_event()
        github = FakeGitHub(self.context)
        self.api.side_effect = github
        result = self.phase("comment")
        self.assertEqual(result["status"], "posted")
        body = github.writes[0][2]["body"]
        self.assertIn("@original-author", body)
        self.assertIn("Analysis unavailable", body)
        self.assertNotIn("No substantial matches", body)
        self.model.assert_not_called()

    def test_comment_without_analysis_state_does_not_claim_clean(self):
        self.state.mkdir()
        (self.state / "prepare.json").write_text(
            json.dumps(self.context), encoding="utf-8"
        )
        github = FakeGitHub(self.context)
        self.api.side_effect = github
        self.assertEqual(self.phase("comment")["status"], "posted")
        self.assertIn("Analysis unavailable", github.writes[0][2]["body"])

    def test_missing_event_and_unwritable_state_still_return_zero(self):
        self.assertEqual(self.phase("prepare")["status"], "unavailable")
        self.assertEqual(self.phase("comment")["status"], "unavailable")
        blocked = self.root / "not-a-directory"
        blocked.write_text("file", encoding="utf-8")
        self.assertEqual(similarity.main(["analyze", "--state-dir", str(blocked)]), 0)
        self.assertIn("::warning::", self.warnings.getvalue())


class ValidateAnalysisTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.prepared = prepared_state()

    def test_findings_and_explicit_empty_results_are_valid(self):
        for result in (finding(), {"candidate_id": NEW, "matches": []}):
            with self.subTest(result=result):
                self.assertEqual(
                    similarity.validate_analysis({"results": [result]}, self.prepared),
                    [result],
                )

    def test_every_candidate_must_be_covered_exactly_once(self):
        self.prepared["candidates"].append(contract("other.json5", "other"))
        for results in ([], [finding()], [finding(), finding()]):
            with self.subTest(results=results):
                with self.assertRaises(similarity.Unavailable):
                    similarity.validate_analysis({"results": results}, self.prepared)

    def test_unknown_candidate_match_and_duplicate_match_are_rejected(self):
        duplicate = finding()
        duplicate["matches"] *= 2
        for result in (
            finding(candidate_id="invented.json5"),
            finding(contract_id="invented.json5"),
            duplicate,
        ):
            with self.subTest(result=result):
                with self.assertRaises(similarity.Unavailable):
                    similarity.validate_analysis({"results": [result]}, self.prepared)

    def test_same_path_and_same_name_tag_are_not_eligible_matches(self):
        self.prepared["corpus"].extend(
            [contract(NEW, "position"), contract("alias.json5", "position")]
        )
        for path in (NEW, "alias.json5"):
            with self.subTest(path=path):
                with self.assertRaises(similarity.Unavailable):
                    similarity.validate_analysis(
                        {"results": [finding(contract_id=path)]}, self.prepared
                    )

    def test_another_tag_of_the_same_name_is_eligible(self):
        older = "robot/position_v0.json5"
        self.prepared["corpus"].append(contract(older, "position", "v0"))
        results = [finding(contract_id=older)]
        self.assertEqual(
            similarity.validate_analysis({"results": results}, self.prepared), results
        )

    def test_malformed_structured_response_is_rejected(self):
        invalid = [
            None,
            [],
            {},
            {"results": "clean"},
            {"results": [{"candidate_id": NEW, "matches": "none"}]},
            {
                "results": [
                    {
                        "candidate_id": NEW,
                        "matches": [
                            {"contract_id": ARM, "similarities": [5], "differences": []}
                        ],
                    }
                ]
            },
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(similarity.Unavailable):
                    similarity.validate_analysis(payload, self.prepared)


class AnalyzeTests(OfflineTestCase):
    def test_successful_inference_requires_valid_structured_results(self):
        prepared = prepared_state()
        self.model.side_effect = None
        self.model.return_value = {"results": [finding()]}
        result = similarity.analyze(prepared)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["results"], [finding()])
        self.model.assert_called_once()
        prompt = self.model.call_args.args[0]
        self.assertIn("Target in the world frame.", prompt)
        self.assertIn("request_message_format", prompt)

    def test_prompt_contains_per_candidate_eligible_ids_and_full_corpus(self):
        prepared = prepared_state()
        prepared["corpus"].extend(
            [
                contract(NEW, "position"),
                contract("alias.json5", "position"),
                contract("older.json5", "position", "v0"),
            ]
        )
        prompt = json.loads(similarity.build_prompt(prepared))
        self.assertEqual(
            set(prompt["candidates"][0]["eligible_contract_ids"]),
            {ARM, GRIPPER, "older.json5"},
        )
        self.assertEqual(prompt["existing_contracts"], prepared["corpus"])

    def test_prompt_size_limit_is_unavailable_without_model_call(self):
        prepared = prepared_state()
        limit = len(similarity.build_prompt(prepared).encode("utf-8")) - 1
        with mock.patch.object(similarity, "MAX_INPUT_BYTES", limit):
            result = similarity.analyze(prepared)
        self.assertEqual(result, {"status": "unavailable", "reason": "input_limit"})
        self.model.assert_not_called()

    def test_missing_secret_has_an_honest_unavailable_result(self):
        del os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
        result = similarity.analyze(prepared_state())
        self.assertEqual(result, {"status": "unavailable", "reason": "missing_token"})
        self.model.assert_not_called()

    def test_missing_or_invalid_model_results_cannot_become_clean(self):
        self.model.side_effect = None
        for response in (
            {"results": []},
            {"results": [finding(contract_id="invented.json5")]},
        ):
            with self.subTest(response=response):
                self.model.return_value = response
                result = similarity.analyze(prepared_state())
                self.assertEqual(result["status"], "unavailable")
                self.assertTrue(result["reason"])

    def test_model_failure_is_unavailable_not_a_clean_review(self):
        self.model.side_effect = similarity.Unavailable("claude")
        result = similarity.analyze(prepared_state())
        self.assertEqual(result, {"status": "unavailable", "reason": "claude"})

    def test_failed_preparation_does_not_infer(self):
        result = similarity.analyze(
            {
                **prepared_state(),
                "status": "unavailable",
                "reason": "Could not read the Git snapshot",
            }
        )
        self.assertEqual(result["status"], "unavailable")
        self.model.assert_not_called()

    def test_empty_corpus_has_explicit_clean_results_without_inference(self):
        prepared = {**prepared_state(), "corpus": []}
        self.assertEqual(similarity.analyze(prepared), clean_analysis(prepared))
        self.model.assert_not_called()


class RenderCommentTests(OfflineTestCase):
    def test_comment_mentions_original_author_not_event_actor(self):
        prepared = prepared_state()
        with mock.patch.dict(os.environ, {"GITHUB_ACTOR": "rerun-reviewer"}):
            body = similarity.render_comment(prepared, clean_analysis(prepared))
        self.assertEqual(body.count("@original-author"), 1)
        self.assertNotIn("@rerun-reviewer", body)

    def test_findings_use_trusted_snapshot_links_and_explanations(self):
        prepared = prepared_state()
        body = similarity.render_comment(
            prepared, {"status": "complete", "results": [finding()]}
        )
        self.assertIn(
            f"https://github.com/{prepared['repository']}/blob/{prepared['head_sha']}/{NEW}",
            body,
        )
        self.assertIn(
            f"https://github.com/{prepared['repository']}/blob/{prepared['base_sha']}/{ARM}",
            body,
        )
        self.assertIn("Both command a Cartesian target.", unescape(body))
        self.assertIn("The arm contract also plans joint motion.", unescape(body))

    def test_untrusted_explanations_cannot_create_mentions_html_or_links(self):
        result = finding()
        result["matches"][0]["similarities"] = [
            "@unwanted <img src=x> [click](https://evil.example/path)"
        ]
        result["matches"][0]["differences"] = ["<https://evil.example> @other-user"]
        body = similarity.render_comment(
            prepared_state(), {"status": "complete", "results": [result]}
        )
        for active_content in (
            "@unwanted",
            "@other-user",
            "<img",
            "<https://evil.example>",
            "[click](https://evil.example/path)",
        ):
            with self.subTest(active_content=active_content):
                self.assertNotIn(active_content, body)
        self.assertIn("@original-author", body)

    def test_clean_no_changes_and_unavailable_are_distinguishable(self):
        prepared = prepared_state()
        clean = similarity.render_comment(prepared, clean_analysis(prepared))
        unchanged = similarity.render_comment(
            {**prepared, "status": "no_changes"},
            {"status": "no_changes", "results": []},
        )
        unavailable = similarity.render_comment(
            prepared,
            {
                "status": "unavailable",
                "results": [],
                "reason": "Claude request timed out",
            },
        )
        self.assertEqual(len({clean, unchanged, unavailable}), 3)
        self.assertNotIn("unavailable", clean.lower())
        self.assertIn("unavailable", unavailable.lower())
        self.assertIn("@original-author", unavailable)


class PublishCommentTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.prepared = prepared_state()
        self.analysis = clean_analysis(self.prepared)
        self.github = FakeGitHub(self.prepared)
        self.api.side_effect = self.github

    def test_fresh_review_creates_author_mention(self):
        result = similarity.comment(self.prepared, self.analysis)
        self.assertEqual(result["status"], "posted")
        self.assertEqual(len(self.github.writes), 1)
        method, path, payload = self.github.writes[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            path.lstrip("/"), "repos/Peppy-bot/contracts-hub/issues/42/comments"
        )
        self.assertIn("@original-author", payload["body"])

    def test_current_api_base_sha_is_valid_after_target_branch_advances(self):
        self.github.pr["base"]["sha"] = self.prepared["base_sha"]
        self.assertEqual(
            similarity.comment(self.prepared, self.analysis)["status"], "posted"
        )

    def test_sticky_comment_requires_bot_ownership_and_searches_all_pages(self):
        marker_body = similarity.render_comment(self.prepared, self.analysis)
        self.github.pages[1] = [
            {
                "id": 10,
                "body": marker_body,
                "user": {"login": "contributor", "type": "User"},
            },
            {
                "id": 11,
                "body": marker_body,
                "user": {"login": "other[bot]", "type": "Bot"},
            },
            {
                "id": 12,
                "body": marker_body,
                "user": {"login": "github-actions[bot]", "type": "User"},
            },
        ] + [
            {
                "id": number,
                "body": "Ordinary comment",
                "user": {"login": "contributor", "type": "User"},
            }
            for number in range(100, 197)
        ]
        self.github.pages[2] = [
            {
                "id": 900,
                "body": marker_body,
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            }
        ]
        result = similarity.comment(self.prepared, self.analysis)
        self.assertEqual(result["status"], "updated")
        self.assertEqual(len(self.github.writes), 1)
        self.assertEqual(
            self.github.writes[0][:2],
            ("PATCH", "repos/Peppy-bot/contracts-hub/issues/comments/900"),
        )
        self.assertTrue(any("page=2" in call[1] for call in self.github.calls))

    def test_stale_head_base_reference_target_tip_or_closed_pr_never_publishes(self):
        for change in ("head", "base_sha", "base_ref", "target_tip", "closed"):
            with self.subTest(change=change):
                github = FakeGitHub(self.prepared)
                if change == "head":
                    github.pr["head"]["sha"] = "d" * 40
                elif change == "base_sha":
                    github.pr["base"]["sha"] = "d" * 40
                elif change == "base_ref":
                    github.pr["base"]["ref"] = "other"
                elif change == "target_tip":
                    github.base_sha = "d" * 40
                else:
                    github.pr["state"] = "closed"
                self.api.side_effect = github
                self.assertEqual(
                    similarity.comment(self.prepared, self.analysis)["status"], "stale"
                )
                self.assertEqual(github.writes, [])

    def test_freshness_is_checked_after_comment_lookup(self):
        def advance_after_lookup(method, path, payload=None):
            result = self.github(method, path, payload)
            if method == "GET" and "/comments?" in path:
                self.github.pr["head"]["sha"] = "d" * 40
            return result

        self.api.side_effect = advance_after_lookup
        self.assertEqual(
            similarity.comment(self.prepared, self.analysis)["status"], "stale"
        )
        self.assertEqual(self.github.writes, [])

    def test_publication_failure_is_unavailable(self):
        self.api.side_effect = similarity.Unavailable("GitHub request failed")
        result = similarity.comment(self.prepared, self.analysis)
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(result["reason"])

    def test_clean_rerun_replaces_previous_findings(self):
        old = similarity.render_comment(
            self.prepared, {"status": "complete", "results": [finding()]}
        )
        self.github.pages[1] = [
            {
                "id": 900,
                "body": old,
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            }
        ]
        self.assertEqual(
            similarity.comment(self.prepared, self.analysis)["status"], "updated"
        )
        body = self.github.writes[0][2]["body"]
        self.assertNotIn("Both command a Cartesian target.", body)
        self.assertEqual(body, similarity.render_comment(self.prepared, self.analysis))


class ClaudeInvocationTests(unittest.TestCase):
    def setUp(self):
        self.env = self.enterContext(
            mock.patch.dict(
                os.environ,
                {
                    "PATH": os.environ["PATH"],
                    "HOME": "/untrusted-home",
                    "CLAUDE_CODE_OAUTH_TOKEN": "test-only-oauth-token",
                    "GH_TOKEN": "github-secret",
                    "GITHUB_TOKEN": "github-secret",
                    "GH_ENTERPRISE_TOKEN": "github-secret",
                    "GITHUB_ENTERPRISE_TOKEN": "github-secret",
                    "GITHUB_ACTOR": "rerun-reviewer",
                    "UNRELATED_SECRET": "unrelated-secret",
                    "ANTHROPIC_BASE_URL": "https://evil.example",
                    "NODE_OPTIONS": "--require=evil.js",
                    "CLAUDE_CONFIG_DIR": "/untrusted-config",
                    "BASH_ENV": "/untrusted-hook",
                },
                clear=True,
            )
        )
        self.enterContext(
            mock.patch.object(
                similarity.shutil, "which", return_value="/trusted/claude"
            )
        )
        self.process = self.enterContext(
            mock.patch.object(similarity.subprocess, "run")
        )
        self.schema = {
            "type": "object",
            "properties": {"results": {"type": "array"}},
            "required": ["results"],
        }
        self.payload = {"results": [finding()]}
        self.process.return_value = subprocess.CompletedProcess(
            ["claude"],
            0,
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "structured_output": self.payload,
                }
            ),
            "",
        )

    def test_tool_free_invocation_and_child_environment_are_isolated(self):
        captured = {}
        response = self.process.return_value

        def inspect_invocation(argv, **kwargs):
            captured.update(argv=argv, **kwargs)
            captured["cwd_entries"] = list(Path(kwargs["cwd"]).iterdir())
            return response

        self.process.side_effect = inspect_invocation
        self.assertEqual(
            similarity.run_claude("Untrusted contract source", self.schema),
            self.payload,
        )
        argv = captured["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertIn("--safe-mode", argv)
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--disable-slash-commands", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertNotIn("--bare", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1]), self.schema)
        self.assertEqual(
            json.loads(argv[argv.index("--mcp-config") + 1]), {"mcpServers": {}}
        )
        self.assertTrue(
            json.loads(argv[argv.index("--settings") + 1])["disableAllHooks"]
        )
        self.assertFalse(captured.get("shell", False))
        self.assertEqual(captured["input"], "Untrusted contract source")
        self.assertGreater(captured["timeout"], 0)
        env = captured["env"]
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "test-only-oauth-token")
        self.assertNotEqual(env["HOME"], "/untrusted-home")
        self.assertNotEqual(env.get("CLAUDE_CONFIG_DIR"), "/untrusted-config")
        for name in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "GH_ENTERPRISE_TOKEN",
            "GITHUB_ENTERPRISE_TOKEN",
            "GITHUB_ACTOR",
            "UNRELATED_SECRET",
            "ANTHROPIC_BASE_URL",
            "NODE_OPTIONS",
            "BASH_ENV",
        ):
            with self.subTest(name=name):
                self.assertNotIn(name, env)
        self.assertNotIn(".git", [path.name for path in captured["cwd_entries"]])

    def test_missing_oauth_secret_is_unavailable_without_spawning(self):
        del os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
        with self.assertRaises(similarity.Unavailable):
            similarity.run_claude("prompt", self.schema)
        self.process.assert_not_called()

    def test_missing_cli_is_unavailable_without_spawning(self):
        with mock.patch.object(similarity.shutil, "which", return_value=None):
            with self.assertRaises(similarity.Unavailable):
                similarity.run_claude("prompt", self.schema)
        self.process.assert_not_called()

    def test_timeout_is_unavailable_without_sleeping(self):
        self.process.side_effect = subprocess.TimeoutExpired("claude", timeout=1)
        with self.assertRaises(similarity.Unavailable):
            similarity.run_claude("prompt", self.schema)

    def test_process_failure_and_failed_or_malformed_envelopes_are_unavailable(self):
        envelopes = [
            (1, "failure"),
            (0, "not JSON"),
            (
                0,
                json.dumps(
                    {"type": "result", "subtype": "error_max_turns", "is_error": True}
                ),
            ),
            (
                0,
                json.dumps(
                    {"type": "result", "subtype": "success", "result": "No overlaps"}
                ),
            ),
            (
                0,
                json.dumps(
                    {"type": "result", "subtype": "success", "structured_output": []}
                ),
            ),
        ]
        for code, stdout in envelopes:
            with self.subTest(code=code, stdout=stdout):
                self.process.return_value = subprocess.CompletedProcess(
                    ["claude"], code, stdout, ""
                )
                with self.assertRaises(similarity.Unavailable):
                    similarity.run_claude("prompt", self.schema)


if __name__ == "__main__":
    unittest.main()
