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

## Pairings

**Pairings** (`peppy_schema: "pairing/v1"`) live here too. A pairing is the same
kind of document as a contract, a shape both sides inherit by reference rather
than duplicate, except that it names *two* roles and both directions of a
bidirectional relationship. Two instances, one per role, are paired 1:1 over it.

```json5
{
  peppy_schema: "pairing/v1",
  manifest: { name: "<pairing_name>", tag: "<tag>" },
  roles: ["<role_a>", "<role_b>"],       // exactly two
  topics: [ /* each entry's `emitted_by` names one of the two roles */ ],
}
```

Pairings declare topics only: no services, no actions. See `robot/joint_link.json5`, `robot/gripper_link.json5`, and `example_robot/deliberation.json5`.

## Use

This repo is consumed by `peppy repo refresh` alongside node and launcher repositories.
