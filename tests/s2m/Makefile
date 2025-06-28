F.schema    = $(wildcard *.schema.json)
F.model     = $(F.schema:%.schema.json=%.model.json)

.PHONY: gen
gen: $(F.model)
%.model.json: %.schema.json
	jsu-simpler $< | jsu-model --loose > $@

.PHONY: clean
clean:
	$(RM) $(F.model)

.PHONY: check
check:
	$(MAKE) clean
	$(MAKE) gen
