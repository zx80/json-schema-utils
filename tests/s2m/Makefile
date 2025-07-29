F.schema    = $(wildcard *.schema.json)
F.model     = $(F.schema:%.schema.json=%.model.json)

MODEL.opts  = --loose --no-fix

.PHONY: gen
gen: $(F.model)
%.model.json: %.schema.json
	jsu-simpler $< | jsu-model $(MODEL.opts) > $@

.PHONY: clean
clean:
	$(RM) $(F.model)

.PHONY: check
check:
	$(MAKE) clean
	$(MAKE) gen
