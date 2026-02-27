F.schema    = $(wildcard *.schema.json)
F.model     = $(F.schema:%.schema.json=%.model.json)

MODEL.opts  = --no-strict --fix

.PHONY: gen
gen: $(F.model)
%.model.json: %.schema.json
	jsu-model $(MODEL.opts) -o $@ $<

.PHONY: clean
clean:
	$(RM) $(F.model)

.PHONY: check
check:
	$(MAKE) clean
	$(MAKE) gen
