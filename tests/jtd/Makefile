SHELL   = /bin/bash
.ONESHELL:

F.jtd       = $(wildcard *.jtd.json)
F.schema    = $(F.jtd:%.jtd.json=%.schema.json)
F.model     = $(F.schema:%.schema.json=%.model.json)

F.gen       = $(F.schema) $(F.model)
F.tmp       = $(F.gen:%.json=%.tmp.json)

MODEL.opts  = --no-strict --fix

.PHONY: gen
gen: $(F.gen)

.PHONY: tmp
tmp: $(F.tmp)

%.schema.tmp.json: %.jtd.json
	jsu-jtd -s -nsk --debug $< > $@

%.model.tmp.json: %.jtd.json
	jsu-jtd -m -nsk --debug $< > $@

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
