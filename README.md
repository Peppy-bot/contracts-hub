# Contracts Hub

A repository of Peppy **contracts** (`peppy_schema: "contract/v1"`).

A contract declares the topics, services, and actions a node must expose to implement it. A producer claims a contract in `manifest.implements` and lists every contract member as an explicit contract-backed entry in its `interfaces` section, using the implementation's `link_id`. A consumer depends on the contract through `manifest.depends_on.contracts` rather than on a specific node, so any implementing producer can satisfy it.

## Adding a contract

Create a new `.json5` file under the relevant category:

```json5
{
  peppy_schema: "contract/v1",
  manifest: {
    name: "<contract_name>",
    tag: "<tag>", // tag is a contract identifier like "v1", not semver (dots forbidden)
    description: [
      "<What the contract is for, in one or two sentences: peppy repo search prints this paragraph.>",
      "<What a caller needs besides: units, frames, the rules to slice arrays.>",
    ],
  },
  interfaces: {
    topics:   [ /* ... */ ],
    services: [ /* ... */ ],
    actions:  [ /* ... */ ],
  }
}
```

The description of a contract is a list of paragraphs, and each topic, service and action has a `description` of one string, right after its `name`. A field of a message format can have a `$description` beside its `$type`: `{ $type: "f64", $description: "<text>" }`. Peppy refuses a contract without its description, or with a member without its description, and reads no rule from a description: `$enum`, marks and failure kinds stay the rules. Notes for the maintainers and the implementers stay comments.

## Geometry fields

Every point, orientation, pose and velocity of a contract or a pairing is written with the same fields in every contract and pairing, as `geometry_msgs` names them:

| Value | Fields |
|---|---|
| point | `position` |
| orientation | `orientation` |
| pose | `position`, `orientation` |
| twist | `linear_velocity`, `angular_velocity` |

- Each value names its frame and its time: the record that holds it gives `frame` and `timestamp` beside the value's fields, in its `header`, or in a record that encloses it. A record of many values at one instant gives one `frame` and one `timestamp` and an array of objects that hold the values' fields, so an array of points is an array of `{ position }`, since peppy has no array of arrays.
- `frame` is a frame as `transforms` names frames: a link of the robot's URDF, `odom` or `map`, or `world` in a simulation contract, whose goals and requests may leave `frame` out for `world`. The robot frame is the root link of the robot's URDF, and its name differs from robot to robot: `describe_sensors` of `sensor_mounts` gives it in `robot_frame`.
- `timestamp` is the time on the clock of `transforms` at which the values hold. A command may leave it out, to be placed at the latest time, as tf2 names the latest time `TimePointZero`. A report gives it, apart from where its member says the values hold at every time, as tf2 stamps a static answer 0 (a static transform, a camera's depth-to-colour pose, a location, the bounds of a workspace, a pose that follows from joint positions alone): there the report leaves it out. An empty result is a value at a time and gives its timestamp, and a record a result does not hold is absent as a whole.
- `position` is [x, y, z] in m, and `orientation` a unit quaternion [x, y, z, w]; a command's `orientation` may be left out where its member says what an absent one means, and is required where its member needs one. A twist is the velocity of the moving frame's origin, `linear_velocity` in m/s and `angular_velocity` in rad/s, both in the frame of its record, as REP 105 places an odometry's twist.
- A value in an item of a record that has its own `position` and `orientation` is relative to that record's pose: a collision object's shapes are posed relative to the object, and a shape's `mesh_vertices` relative to the shape. The workflow director refuses a `$ref` to such a value.
- Two records hold `child_frame`: an odometry record `{ frame, child_frame, timestamp, pose, twist }`, as `nav_msgs/Odometry` gives its pose in `frame` and its twist in `child_frame`, and a transform record `{ frame, child_frame, position, orientation }` under one `timestamp`, as each transform of `transforms` is.
- A field that a member reads in some requests alone is optional, and the member says when it reads it: an object that `apply_collision_objects` removes leaves out its `frame`, pose and `shapes`, and a reference of `scene_workspace` gives `point` in the form of a point alone.
- A sensor message's `header` holds `frame`, the sensor's frame, `timestamp` and `capture_index`, the capture counter.
- A planar contract takes these fields too, with z 0 and turns about +z, and refuses another pose or twist with `rejected`.

```json5
// The fields, as each contract and pairing writes them.
frame: { $type: "string", $description: "The frame of the record's values, as transforms names frames; a twist beside a child_frame is in child_frame, and a sensor's values are in frame through the sensor's own geometry." },
frame: { $type: "string", $optional: true, $description: "The frame of the record's values, as transforms names frames; a twist beside a child_frame is in child_frame, and a sensor's values are in frame through the sensor's own geometry." },  // in a goal or a request of a simulation contract, where an absent one names world
child_frame: { $type: "string", $description: "The frame whose pose in frame the record gives, as transforms names frames." },
timestamp: { $type: "time", $optional: true, $description: "The time on the clock of transforms at which the values hold. A command leaves it out for the latest time; a report leaves it out for values that hold at every time." },  // in a command, and in a report whose member names values that hold at every time
timestamp: { $type: "time", $description: "The time on the clock of transforms at which the values hold." },  // in every other report
position: { $type: "array", $items: "f64", $length: 3, $description: "x, y, z (m)." },
orientation: { $type: "array", $items: "f64", $length: 4, $optional: true, $description: "A unit quaternion [x, y, z, w], or absent for none." },  // in a goal or a request whose member says what an absent one means
orientation: { $type: "array", $items: "f64", $length: 4, $description: "A unit quaternion [x, y, z, w]." },  // in a result, a response, feedback or a topic, and in a goal or a request whose member needs one
linear_velocity: { $type: "array", $items: "f64", $length: 3, $description: "x, y, z (m/s)." },
angular_velocity: { $type: "array", $items: "f64", $length: 3, $description: "About x, y, z (rad/s)." },
```

## Marks

A mark is a name that a contract gives to a member (`marks: ["<mark>"]` on a topic, a service or an action, after its `failure_kinds`) or to a field of a message format (`{ $type: "string", $marks: ["<mark>"] }`). The side that owns a mark reads it and acts on it. Peppy acts only on the marks that it owns, and keeps each other mark as written for its clients.

Peppy owns one mark, `moves_robot`. It is on each member of a contract that an instance of a robot or a device serves, when the member can move a part of that robot, the gripper included, or change the state of that device, such as `move_to_home` of `postures`. Each MCP server, `peppy node call` and each lease holder asks the daemon (`robot_leases.check_move`) before each call of a member with this mark. A member that only stops a motion, such as `stop` of `limb_motion`, a member that only reads or checks, and each member of the simulation contracts have no mark.

The workflow side owns four marks, which the workflow director reads to check a workflow: `item_id` on a field that holds an item id, so a workflow passes its value only by `$ref` to a field with the same mark from the same node instance; `reaches_for_item` on a member that reaches for an item, such as `grab_item` of `item_manipulation`, so a lane that calls it checks first that the robot reaches its work zone, with a `kind: "reach"` assumption, or the item, with a reach check; `checks_reach` on the boolean field of a result that tells whether the robot reaches every point of the request, such as `all_workable` of `check_positions` of `workspace`, so a call of the member with `as` and a `done_when` that is this field of its result is a reach check: before a member with the mark `reaches_for_item` on every path of the lane, with points read from the same result or observation as the item, it checks in the run that the robot reaches the item; and `location` on a string field that receives the name of a location that the node knows through `locations:v1`, so a workflow gives it only a `{ $location }` of a location it declares.

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
including their descriptions, comments, topics, services, actions, and action goals. It looks for meaningful
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
