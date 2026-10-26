# Contracts Hub

A repository of Peppy **contracts** (`peppy_schema: "contract/v1"`).

A contract declares the topics, services, and actions a node must expose to implement it. A producer claims a contract in `manifest.implements` and lists every contract member as an explicit contract-backed entry in its `interfaces` section, using the implementation's `link_id`. A consumer depends on the contract through `manifest.depends_on.contracts` rather than on a specific node, so any implementing producer can satisfy it.

## Adding a contract

Create a new `.json5` file under the relevant category:

```json5
{
  peppy_schema: "contract/v1",
  manifest: { name: "<contract_name>", tag: "<tag>" }, // tag is a contract identifier like "v1", not semver (dots forbidden)
  interfaces: {
    topics:   [ /* ... */ ],
    services: [ /* ... */ ],
    actions:  [ /* ... */ ],
  }
}
```

## Marks

A mark is a name that a contract gives to a member (`marks: ["<mark>"]` on a topic, a service or an action, after its `failure_kinds`) or to a field of a message format (`{ $type: "string", $marks: ["<mark>"] }`). The side that owns a mark reads it and acts on it. Peppy acts only on the marks that it owns, and keeps each other mark as written for its clients.

Peppy owns one mark, `moves_robot`. It is on each member of a contract that an instance of a robot or a device serves, when the member can move a part of that robot, the gripper included, or change the state of that device, such as `move_to_home` of `postures`. Each MCP server, `peppy node call` and each lease holder asks the daemon (`fleet.check_move`) before each call of a member with this mark. A member that only stops a motion, such as `stop` of `limb_motion`, a member that only reads or checks, and each member of the simulation contracts have no mark.

The mark list, `marks.json5`, names each mark, its owner and its meaning. A client side adds a mark of its own with one entry that names the client side as its owner. The `check-marks` job of the **Tests** workflow refuses a contract with a mark that the list does not name, so a misspelled mark fails the CI and never removes a check without notice. To run the check, with the environment of [Testing the automation](#testing-the-automation):

```sh
/tmp/contracts-hub-tests/bin/python .github/scripts/check_marks.py
```

## Use

This repo is consumed by `peppy repo refresh` alongside node and launcher repositories.

## Adding an item to this repository

This repository publishes what `peppy_repository.json5` says it publishes, and nothing else. An item
that is not listed there is invisible to peppy, so after adding, moving, or renaming a contract, run:

```sh
peppy repo index .
```

Commit the updated `peppy_repository.json5` alongside your change, and run
`peppy repo index --check` before pushing: it fails if the index has drifted
from the repository, naming the file and the identity involved.

Generation refuses, naming both files, if your change claims a `name:tag` another one already
publishes. Rename yours: within one repository, a `name:tag` is claimed by exactly one file.

## Advisory similarity review

The **Contract similarity** workflow runs when a pull request is opened, updated, reopened, or
edited. Claude compares added and modified contracts with the target branch's contracts,
including their comments, topics, services, actions, and action goals. It looks for meaningful
overlap in purpose, not just matching field names, and explains relevant differences. New
contracts are included even before they appear in `peppy_repository.json5`.

One bot comment mentions the PR author and is updated on subsequent runs. It reports possible
matches with source links, no substantial matches, no changed contracts, or an unavailable
review. A contract never matches itself or its own earlier revision, and contracts removed by
the PR are excluded. Documentation-only and deletion-only PRs do not call Claude. Results
identify the reviewed revisions; an outdated run does not replace the comment for a newer PR
revision.

Each changed contract receives up to three matches. The complete input is limited to 1 MiB,
with at most 20 changed contracts, 250 existing contracts, 500 JSON5 files per snapshot, and
128 KiB per file. Claude has a six-minute timeout. Exceeded limits produce an unavailable
review, not a truncated comparison or a claim of uniqueness.

This review is advisory, not a merge gate or a guarantee of uniqueness. Similarities, missing
credentials, and analysis failures do not fail the workflow. If GitHub rejects the comment,
the workflow logs a warning. The **Tests** workflow, whose checks a merge requires, stays
independent of it.

### Claude authentication

Configure the **`CLAUDE_CODE_OAUTH_TOKEN`** Actions secret for this repository, using a token
created with `claude setup-token`. An organization secret must explicitly grant this repository
access. A secret stored only in another repository, such as `peppy`, is not shared automatically.
Until the secret is configured, contract changes receive an unavailable-review notice.

The workflow uses Claude Code `2.1.269` with `claude-opus-5`. Its `pull_request_target` job runs
only trusted base-revision scripts. PR files are read as Git objects, never checked out or
executed. Claude runs without tools, MCP servers, skills, or repository customizations, in an
isolated temporary environment without the GitHub token. Separate trusted code validates the
response and posts the comment.

Target-triggered automation runs from the base branch, so the workflow and its helper must be
present there to review PRs. The `contract-similarity-tests` job of the **Tests** workflow
separately tests proposed automation changes without Claude credentials or write permissions.

### Testing the automation

Run the deterministic tests without making Claude calls or posting GitHub comments:

```sh
python3 -m venv /tmp/contracts-hub-tests
/tmp/contracts-hub-tests/bin/python -m pip install -r .github/scripts/requirements.txt
/tmp/contracts-hub-tests/bin/python -m unittest discover -s .github/scripts -p 'test_*.py' -v
```
