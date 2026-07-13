# JSON Schema Utils Backlog

## JSU 0.9.13 on 2026-07-13

- format: uri or uri-reference (RFC3986)

## JSU 0.9.12 on 2026-07-10

- front: add short option for `--backend`
- convert: fix property sharing which was having strange side effects

## JSU 0.9.11 on 2026-06-22

- fix overzealous `then`/`else` simplification which could ignore nested conditions

## JSU 0.9.10 on 2026-06-20

- front: reduce version verbosity
- convert: fix property override issue when distributing object onto `oneOf`
- front: look for schema file with suffixes
- simpler: fix `propertyNames` to `patternProperties` pattern

## JSU 0.9.9 on 2026-05-09

- front: try to recompute version when under dev
- front: do not show backend version for `jsu-model`
- doc: add a separate `VERSION.md` file

## JSU 0.9.8 on 2026-05-07

- front: add git hash to `--version` output
- front: also show `jmc` git hash if available
- front: use dynamic version extraction

## JSU 0.9.6 on 2026-04-25

- front: add `--precompiled` option forwarded to `jmc` backend

## JSU 0.9.5 on 2026-04-24

- front: allow to call scripts as a function

## JSU 0.9.4 on 2026-04-23

- reduce verbosity about `$vocabulary`

## JSU 0.9.3 on 2026-04-10

- tests with more languages: bowtie with C, JS, java, perl
- convert handle `not` by switching to `oneOf`
- convert fix missing escaping on string constants
- fix unintentional override of jmc options on forwarding
- refactor resolver stuff to reuse it for vocabularies
- support for $vocabulary by removing disactivated keywords
- make test runner report failures with status
- add `--format` to test runner
- compiler: set format default depending on vocabularies
- fix regex `[a|A]`… to `[aA]` to possibly `/a/i`
- fix regex with useless or missing parentheses
- stats: detect regex fixes `^foo|bla$`, `[x|X]`…
- format rely on extensions (color, rel jsonpt…)

## JSU 0.9.2 on 2026-03-13

- add `--runtime` option to show runtime directory

## JSU 0.9.1 on 2026-03-08

- improve conversion of int/float enums and consts
- improve conversion with mixed minContains/maxContains and other array constraints
- improve handling of patternProperties merging
- fix conversion of `json-model.schema.json`
- be listed on [bowtie](https://bowtie.report/)
- make `jsu-test-runner` accepts a single test object
- make `jsu-model` not pedantic by default (`--no-strict`)
- improve support for `unevaluatedProperties` on common use cases
- show default values on `--help`
- simpler possibly remove all-types lists

## JSU 0.9.0 on 2026-02-27

- improve _merge_ to reject some cases
- add `.in` extension support to JMC
- get 100% on _draft7_
- get 100% on _draft6_
- get 100% on _draft4_
- get 100% on _draft3_
- add implementation to [bowtie](https://docs.bowtie.report/en/stable/)
- improve `propertyNames` handling with defs, requires some refactoring
- cleanup direct uses of quote/unquote in simplify
- add `--loose` option for numbers
- add `--out file` option to `jsu-model`
