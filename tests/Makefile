SHELL   = /bin/bash
.ONESHELL:


F.json      = $(wildcard *.schema.json)
F.inline    = $(F.json:%.schema.json=%.inline.json)
F.simpler   = $(F.json:%.schema.json=%.simpler.json)
F.stats     = $(F.json:%.schema.json=%.stats.json)
F.pretty    = $(F.json:%.schema.json=%.pretty.json)

.PHONY: clean
clean:
	$(RM) $(F.pretty)

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
