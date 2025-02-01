# JSON Schema Utils

Random utilities to manipulate JSON Schema.

## Installation

```sh
pip install git+https://github.com/zx80/json-schema-utils.git
```

## Inline References

Replace references `$ref` by their definitions.

```sh
jsu-inline tests/number.json
jsu-inline tests/obj.json
jsu-inline tests/rec.json
jsu-inline -m "file:// ./tests" tests/inc.json
```

## TODO

Testing.
CI.
