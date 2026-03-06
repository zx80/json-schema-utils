# JSON Schema Utils Backlog

## JSU schema compilation with JMC backend

- [x] improve conversion of int/float enums and consts
- [x] improve conversion with mixed minContains/maxContains and other array constraints
- [x] improve handling of patternProperties merging
- [x] fix conversion of `json-model.schema.json`
- [x] be listed on [bowtie](https://bowtie.report/)
- [x] make `jsu-test-runner` accepts a single test object
- [x] make `jsu-model` not pedantic by default (`--no-strict`)
- [x] improve support for `unevaluatedProperties` on common use cases
- [x] show default values on `--help`
- [ ] improve support for `unevaluatedProperties` with `if`/`then`/`else`?
- [ ] improve support for `unevaluatedProperties` with `patternProperties`?
- [ ] discuss strategies to address version 9 (2020) specific features
- [ ] move typing out to simplify the generated code
- [ ] get 100% on _draft2019-09_
- [ ] get 100% on _draft2020-12_
- [ ] add `.in` support with constraints
- [ ] tests with all languages, not just Python
- [ ] list compiler current limitations
- [ ] run some optional tests, eg _format_
- [ ] put typing result in "$type" instead of "type" to help with fixing?
- [ ] add an `--auto` flag to set options depending on schema versions?

## Dones

- [x] improve _merge_ to reject some cases
- [x] add `.in` extension support to JMC
- [x] get 100% on _draft7_
- [x] get 100% on _draft6_
- [x] get 100% on _draft4_
- [x] get 100% on _draft3_
- [x] add implementation to [bowtie](https://docs.bowtie.report/en/stable/)
- [x] improve `propertyNames` handling with defs, requires some refactoring
- [x] cleanup direct uses of quote/unquote in simplify
- [x] add `--loose` option for numbers
- [x] add `--out file` option to `jsu-model`
