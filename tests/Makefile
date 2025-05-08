SHELL   = /bin/bash
.ONESHELL:

F.schema      = $(wildcard *.schema.json)

# derived
F.inline    = $(F.schema:%.schema.json=%.inline.json)
F.simpler   = $(F.schema:%.schema.json=%.simpler.json)
F.stats     = $(F.schema:%.schema.json=%.stats.json)
F.pretty    = $(F.schema:%.schema.json=%.pretty.json)
F.check     = person.check1.out person.check2.out author.check1.out author.check2.out

# all
F.gen       = $(F.inline) $(F.simpler) $(F.stats) $(F.pretty) $(F.check)

.PHONY: check
check: check.local check.sub

.PHONY: check.local
check.local:
	$(MAKE) clean
	$(MAKE) gen

.PHONY: check.sub
check.sub:
	$(MAKE) -C s2m check

.PHONY: clean
clean:
	$(RM) $(F.gen)

.PHONY: gen
gen: $(F.gen)

.PHONY: inline
inline:
	$(RM) $(F.inline)
	$(MAKE) $(F.inline)

%.inline.json: %.schema.json
	jsu-inline -m "file:// ." -m ":// ." $< > $@

.PHONY: simpler
simpler:
	$(RM) $(F.simpler)
	$(MAKE) $(F.simpler)

%.simpler.json: %.schema.json
	jsu-simpler $< > $@

.PHONY: stats
stats:
	$(RM) $(F.stats)
	$(MAKE) $(F.stats)

%.stats.json: %.schema.json
	jsu-stats $< > $@

.PHONY: pretty
pretty:
	$(RM) $(F.pretty)
	$(MAKE) $(F.pretty)

%.pretty.json: %.schema.json
	jsu-pretty $< > $@

# schema validation
%.check1.out: %.schema.json
	set -o pipefail
	shopt -s nullglob
	jsu-check --engine jsonschema $< $*.*.{true,false}.json 2> $@.err | sort > $@
	cat $@.err >> $@
	$(RM) $@.err

%.check2.out: %.schema.json
	set -o pipefail
	shopt -s nullglob
	jsu-check --engine jschon $< $*.*.{true,false}.json 2> $@.err | sort > $@
	sed -e 's/uuid:[-0-9a-f]*#/uuid:<uuid>#/' $@.err >> $@
	$(RM) $@.err
