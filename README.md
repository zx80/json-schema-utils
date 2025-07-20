# JSON Schema Utils

Random utilities to analyze and manipulate JSON Schema.

## Installation

Install latest version with `pip` from
[PyPI](https://pypi.org/project/json-schema-utils) or directly from
[GitHub](https://github.com/zx80/json-schema-utils):

```sh
python -m venv venv
source venv/bin/activate
# from PyPI:
pip install json_schema_utils
# OR from latest sources:
pip install git+https://github.com/zx80/json-schema-utils.git
```

## Inline Schema References

Replace references `$ref` by their definitions.

```sh
# no $id
jsu-inline -m "file:// ./tests" tests/*.schema.json
# with $id
jsu-inline -a tests/foo.schema.json
```

## Simplify Schema

Apply various schema simplifications:

- remove type-incompatible keywords and formats, with warnings.
- try to move up list-of-one-schema `*Of`.
- simplify type lists.
- change list-of-one `enum` to `const`.
- detect some cases of infeasible schemas.
- remove uneffective keywords in corner cases.

```sh
jsu-simpler tests/*.schema.json
```

## Check JSON Values against a Schema

Check a JSON values match a given schema using either
[jsonschema](https://github.com/python-jsonschema/jsonschema) or
[jschon](https://github.com/marksparkza/jschon) implementations.

```sh
jsu-check tests/foo.schema.json tests/foo.*.value.json
```

## JSON Schema Stats and Issues

Generate a report about JSON schemas, including possible bugs.

```sh
jsu-stats tests/*.schema.json
```

This script is extracted from [JSON Schema Stats](https://github.com/clairey-zx81/json-schema-stats)
which has been updated to depend on this module.

## JSON Prettyprinter

```sh
jsu-pretty --indent 2 --sort-keys tests/*.schema.json
```

You could also use `jq .` for this purpose.

## JSON Schema to JSON Model Conversion

Convert a subset of JSON Schema to JSON Model.
The subset should comply with some restrictions described in Section 6 of
[An Analysis of Defects in Public JSON Schemas](https://minesparis-psl.hal.science/hal-04415517/file/A-794-DepotHAL.pdf)
by Claire Yannou-Medrala and Fabien Coelho:

- `const`, `enum`, `$ref`, `type`, `allOf`, `anyOf`, `oneOf` should be exclusive.
- some keywords are not supported: `multipleOf`, `contains`
- conditions `if then else` are translated to the logical equivalent:
  `{if: C, then: T, else: E}` is _(C and T) or (not C and E)_

```sh
jsu-model test/foo.schema.json
```

## TODO

- Testing. CI.
- stats: warn instead of errors on unsure issues under `if`/`then`/`else`/`not`.
- propagate non type under containers (`*Of`, `if`, `then`, `else`, reference?)
  to reduce false positive errors/warnings.
- simplify: deduplicate constants in enum?
