# JSON Schema Utils

Random utilities to manipulate JSON Schema.

## Installation

```sh
pip install git+https://github.com/zx80/json-schema-utils.git
```

## Inline References

Replace references `$ref` by their definitions.

```sh
jsu-inline -m "file:// ./tests" tests/*.schema.json
```

## Simplify Schema

```sh
jsu-simpler tests/*.schema.json
```

## Check Schema Values

Check a JSON values match a given schema.

```sh
jsu-check tests/foo.schema.json tests/foo.*.value.json
```

## TODO

- Testing. CI.
- Move stats script here?
- Check script?
