# JSON Schema Utils Backlog

## JSU 0.9.9

- [x] front: try to recompute version when under dev
- [x] front: do not show backend version for `jsu-model`
- [x] doc: add a separate `VERSION.md` file

## JSU 0.9.8

- [x] front: add git hash to `--version` output
- [x] front: also show `jmc` git hash if available
- [x] front: use dynamic version extraction

## JSU 0.9.6

- [x] front: add `--precompiled` option forwarded to `jmc` backend

## JSU 0.9.5

- [x] front: allow to call scripts as a function

## JSU 0.9.4

- [x] reduce verbosity about `$vocabulary`

## JSU 0.9.3

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
- [x] format rely on extensions (color, rel jsonpt…)

## JSU 0.9.2

- [x] add `--runtime` option to show runtime directory

## JSU 0.9.1

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

## JSU 0.9.0

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
