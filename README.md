# JSON Schema Utils

Random utilities to analyze, manipulate, simplify, convert or compile JSON Schema.

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

Check a JSON values match a given schema using
`jmc` ([jsu-compile](https://github.com/zx80/json-schema-utils) with
[jmc](https://json-model.org/) dynamic Python backend),
[`jsonschema`](https://github.com/python-jsonschema/jsonschema) or
[`jschon`](https://github.com/marksparkza/jschon)
implementations.

```sh
jsu-check tests/foo.schema.json tests/foo.*.value.json
```

Note: the corresponding external dependencies must be installed.

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

The converter is expected to _fully_ supports JSON Schema draft3 to draft7.

It _partially_ supports draft 2019-09 and 2020-12.
In particular, _vocabularies_ are fully supported.
However, there is a limited support for some features:

- _dynamic_ anchors and references
- _unevaluated_ items and properties

Moreover, this is a software, hence there may be bugs.

```sh
jsu-model -o foo.model.json foo.schema.json
```

## JSON Schema Compiler

Convert the input schema and generate C, JS, Python, Java, Perl or even PL/pgSQL code.

The compiler first converts the schema to a model (see previous command), then
proceeds to compile the generated model to actual code using the
[JSON Model Compiler](https://json-model.org/) as a backend.

```sh
# generate a python script
jsu-compile -o some.py some.schema.json
# run the script to validate values
./some.py val1.json val2.json
```

The generated code (here the `some.py` Python script) needs some runtime which
is installed with the compiler python module.
Other languages require specific runtimes, which are available in the
`docker.io/zx80/jmc` container image, or can be installed independently,
see [JSON Model HOWTO](https://json-model.org/#/HOWTO).

## TODO

- propagate non type under containers (`*Of`, `if`, `then`, `else`, reference?)
  to reduce false positive errors/warnings.
- simplify: deduplicate constants in enum?
