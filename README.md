# JSON Schema Utils

Random utilities to manipulate JSON Schema.

## Installation

```sh
python -m venv venv
source venv/bin/activate
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

## JSON Schema Stats and Issues

Generate a report about JSON schemas, including possible bugs.

```sh
jsu-stats tests/*.schema.json
```

This scripts is extracted from [JSON Schema Stats](https://github.com/clairey-zx81/json-schema-stats).

## TODO

- Testing. CI.
