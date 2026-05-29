# interfaces_hub

A repository of Peppy **conformance interfaces** (`peppy_schema: "interface_v1"`).

An interface declares the topics, services, and actions a node must expose to "conform" to it. A producer node claims an interface by listing it under `interfaces.conforms_to` in its `peppy.json5`; a consumer depends on the interface through `manifest.depends_on.interfaces` rather than on a specific node, so any conforming implementation can satisfy it.

## Adding an interface

Create a new `.json5` file under the relevant category:

```json5
{
  peppy_schema: "interface_v1",
  manifest: { name: "<interface_name>", tag: "<tag>" }, // tag is a contract identifier like "v1" — not semver (dots forbidden)
  interfaces: {
    topics:   [ /* ... */ ],
    services: [ /* ... */ ],
    actions:  [ /* ... */ ],
  }
}
```

## Use

This repo is consumed by `peppy repo update` alongside node and launcher repositories.
