SHELL   = /bin/bash
.ONESHELL:

F.json      = $(wildcard *.schema.json)
F.inline    = $(F.json:%.schema.json=%.inline.json)

.PHONY: inline
inline:
	$(RM) $(F.inline)
	$(MAKE) $(F.inline)

%.inline.json: %.schema.json
	jsu-inline -m "file:// ." $< > $@
