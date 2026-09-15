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
review. Contracts do not match themselves, and contracts removed by the PR are excluded.
Documentation-only and deletion-only PRs do not call Claude. Results identify the reviewed
revisions; an outdated run does not replace the comment for a newer PR revision.

Each changed contract receives up to three matches. The complete input is limited to 1 MiB,
with at most 20 changed contracts, 250 existing contracts, 500 JSON5 files per snapshot, and
128 KiB per file. Claude has a six-minute timeout. Exceeded limits produce an unavailable
review, not a truncated comparison or a claim of uniqueness.

This review is advisory, not a merge gate or a guarantee of uniqueness. Similarities, missing
credentials, and analysis failures do not fail the workflow. If GitHub rejects the comment,
the workflow logs a warning. The repository-index check remains independent.

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
present there to review PRs. The **Contract similarity tests** workflow separately tests proposed
automation changes without Claude credentials or write permissions.

### Testing the automation

Run the deterministic tests without making Claude calls or posting GitHub comments:

```sh
python3 -m venv /tmp/contracts-hub-tests
/tmp/contracts-hub-tests/bin/python -m pip install -r .github/scripts/requirements.txt
/tmp/contracts-hub-tests/bin/python -m unittest discover -s .github/scripts -p 'test_*.py' -v
```
