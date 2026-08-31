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
