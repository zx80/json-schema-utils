F.jtd       = $(wildcard *.jtd.json)
F.schema    = $(wildcard *.schema.json) $(F.jtd:%.jtd.json=%.schema.json)
F.model     = $(F.schema:%.schema.json=%.model.json)

F.gen       = $(F.jtd:%.jtd.json=%.schema.json) $(F.model)

MODEL.opts  = --no-strict --fix

.PHONY: gen
gen: $(F.gen)

%.schema.json: %.jtd.json
	jsu-jtd -s -nsk --debug $< > $@

%.model.json: %.jtd.json
	jsu-jtd -m -nsk --debug $< > $@

%.model.json: %.schema.json
	jsu-model --quiet $(MODEL.opts) -o $@ $<

.PHONY: clean
clean:
	$(RM) $(F.gen)

.PHONY: check
check:
	$(MAKE) clean
	$(MAKE) gen

.PHONY: check.jtd
check.jtd:
	$(RM) $(F.jtd:%.jtd.json=%.model.json) $(F.jtd:%.jtd.json=%.schema.json)
	$(MAKE) gen
