# JSON Schema Utils Backlog

## JSU schema compilation with JMC backend

- [x] reduce verbosity about `$vocabulary`
- [x] front: allow to call scripts as a function
- [x] front: add `--precompiled` option forwarded to `jmc` backend
- [x] format rely on extensions (color, rel jsonpt…)
- [x] front: add git hash to `--version` output
- [ ] stats: missing unique?
- [ ] front: look for schema file with suffixes
- [ ] front: allow configuring from env or a file?
- [ ] format: uri or uri-reference (RFC3986), uri-template (RFC6570)
- [ ] format: iri or iri-reference (RFC3987)
- [ ] format: regex see [Section 6.4](https://datatracker.ietf.org/doc/html/draft-bhutton-json-schema-01#name-regular-expressions) for restrictions
- [ ] format: email (RFC5321), idn-email (RFC6531)
- [ ] format: hostname (RFC1123) with punycode (RFC5890), idn-hostname (add RFC5890)
- [ ] convert merge `allOf` before proceeding when possible
- [ ] simpler remove `tests/string_03.simpler.json` redundant `$ref` on merge
- [ ] improve `unevaluatedItems` support (wip)
- [ ] improve support for `unevaluatedProperties` with `if`/`then`/`else`?
- [ ] improve support for `unevaluatedProperties` with `patternProperties`?
- [ ] fixme `unevaluatedProperties: false` is simpler for jm vs js…
- [ ] improve support for `unevaluatedProperties` by merging `allOf` subschemas
- [ ] discuss strategies to address version 9 (2020) specific features
- [ ] move typing out to simplify the generated code
- [ ] get 100% on _draft2019-09_
- [ ] get 100% on _draft2020-12_
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
- [x] improve conversion of int/float enums and consts
- [x] improve conversion with mixed minContains/maxContains and other array constraints
- [x] improve handling of patternProperties merging
- [x] fix conversion of `json-model.schema.json`
- [x] be listed on [bowtie](https://bowtie.report/)
- [x] make `jsu-test-runner` accepts a single test object
- [x] make `jsu-model` not pedantic by default (`--no-strict`)
- [x] improve support for `unevaluatedProperties` on common use cases
- [x] show default values on `--help`
- [x] simpler possibly remove all-types lists
- [x] add `--runtime` option to show runtime directory
- [x] tests with more languages: bowtie with C, JS, java, perl
- [x] convert handle `not` by switching to `oneOf`
- [x] convert fix missing escaping on string constants
- [x] fix unintentional override of jmc options on forwarding
- [x] refactor resolver stuff to reuse it for vocabularies
- [x] support for $vocabulary by removing disactivated keywords
- [x] make test runner report failures with status
- [x] add `--format` to test runner
- [x] compiler: set format default depending on vocabularies
- [x] fix regex `[a|A]`… to `[aA]` to possibly `/a/i`
- [x] fix regex with useless or missing parentheses
- [x] stats: detect regex fixes `^foo|bla$`, `[x|X]`…
