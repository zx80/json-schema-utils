SHELL   = /bin/bash
.ONESHELL:

F.schema    = $(wildcard *.schema.json)
F.model     = $(F.schema:%.schema.json=%.model.json)

F.gen       = $(F.model)
F.tmp       = $(F.gen:%.json=%.tmp.json)

MODEL.opts  = --no-strict --fix

.PHONY: gen
gen: $(F.gen)

.PHONY: tmp
tmp: $(F.tmp)

%.model.tmp.json: %.schema.json
	jsu-model --quiet $(MODEL.opts) -o $@ $<

%.json: %.tmp.json
	mv $< $@

.PHONY: clean
clean:
	$(RM) $(F.tmp)

.PHONY: cleaner
cleaner: clean
	$(RM) $(F.gen)

.PHONY: check
check: $(F.tmp)
	bad=
	for tmp in $(F.tmp) ; do
	  ref=$${tmp/.tmp./.}
	  if ! cmp $$ref $$tmp ; then
	    echo "# $$ref KO"
	    bad=1
	  else
	    $(RM) $$tmp
	  fi
	done
	! [ "$$bad" ]
