SHELL   = /bin/bash
.ONESHELL:

F.schema      = $(wildcard *.schema.json)

# derived
F.inline    = $(F.schema:%.schema.json=%.inline.json)
F.simpler   = $(F.schema:%.schema.json=%.simpler.json)
F.stats     = $(F.schema:%.schema.json=%.stats.json)
F.pretty    = $(F.schema:%.schema.json=%.pretty.json)

F.json      = $(F.inline) $(F.simpler) $(F.stats) $(F.pretty)

VALIDATIONS = person author
F.out       = $(addsuffix .check0.out, $(VALIDATIONS)) \
              $(addsuffix .check1.out, $(VALIDATIONS)) \
              $(addsuffix .check2.out, $(VALIDATIONS))

# all
F.gen       = $(F.json) $(F.out)
F.tmp       = $(F.json:%.json=%.tmp.json) $(F.out:%.out=%.tmp.out)

D.sub       = jtd s2m

.PRECIOUS: $(F.gen)

.PHONY: check
check: check.local $(SUB:%=%.check)

.PHONY: check.local
check.local: $(F.tmp)
	bad=
	for tmp in $(F.tmp) ; do
	  ref=$${tmp//.tmp./.}
	  if ! cmp $$tmp $$ref ; then
	    echo "# $$ref KO"
	    bad=1
	  else
	    $(RM) $$tmp
	  fi
	done
	! [ "$$bad" ]

# forward tasks
%.check:
	$(MAKE) -C $* check

%.clean:
	$(MAKE) -C $* clean

%.cleaner:
	$(MAKE) -C $* cleaner

#
# CLEAN
#
.PHONY: clean
clean: clean.local $(SUB:%=%.clean)

.PHONY: clean.local
clean.local:
	$(RM) $(F.tmp)

.PHONY: cleaner
cleaner: cleaner.local $(SUB:%=%.cleaner)

.PHONY: cleaner.local
cleaner.local:
	$(RM) $(F.gen)

#
# GENERATE
#
.PHONY: gen
gen: $(F.gen)

.PHONY: tmp
tmp: $(F.tmp)

%.json: %.tmp.json
	mv $< $@

%.out: %.tmp.out
	mv $< $@

.PHONY: inline
inline:
	$(RM) $(F.inline)
	$(MAKE) $(F.inline)

defref_0.inline.tmp.json:
	touch $@

%.inline.tmp.json: %.schema.json
	jsu-inline -m "file://=." -m "://=." $< > $@

.PHONY: simpler
simpler:
	$(RM) $(F.simpler)
	$(MAKE) $(F.simpler)

%.simpler.tmp.json: %.schema.json
	jsu-simpler $< > $@

.PHONY: stats
stats:
	$(RM) $(F.stats)
	$(MAKE) $(F.stats)

%.stats.tmp.json: %.schema.json
	jsu-stats $< > $@

.PHONY: pretty
pretty:
	$(RM) $(F.pretty)
	$(MAKE) $(F.pretty)

%.pretty.tmp.json: %.schema.json
	jsu-pretty $< > $@

# schema validation
%.check0.tmp.out: %.schema.json
	set -o pipefail
	shopt -s nullglob
	jsu-check --engine jmc $< $*.*.{true,false}.json 2> $@.err | sort > $@
	sed -e 's/uuid:[-0-9a-f]*#/uuid:<uuid>#/' $@.err >> $@
	$(RM) $@.err

%.check1.tmp.out: %.schema.json
	set -o pipefail
	shopt -s nullglob
	jsu-check --engine jsonschema $< $*.*.{true,false}.json 2> $@.err | sort > $@
	cat $@.err >> $@
	$(RM) $@.err

%.check2.tmp.out: %.schema.json
	set -o pipefail
	shopt -s nullglob
	jsu-check --engine jschon $< $*.*.{true,false}.json 2> $@.err | sort > $@
	sed -e 's/uuid:[-0-9a-f]*#/uuid:<uuid>#/' $@.err >> $@
	$(RM) $@.err
