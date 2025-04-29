F.schema    = $(wildcard *.schema.json)
F.model     = $(F.schema:%.schema.json=%.model.json)

.PHONY: clean
clean:
	$(RM) $(F.model)

.PHONY: gen
gen: $(F.model)

%.model.json: %.schema.json
	jsu-model $< > $@
