# Makefile for the master's thesis
# Usage: make        -- compile main.pdf
#        make clean  -- remove generated files

MAIN := main
LATEXMK := latexmk

.PHONY: all clean

all:
	$(LATEXMK) -pdf -interaction=nonstopmode -synctex=1 $(MAIN)

clean:
	$(LATEXMK) -C $(MAIN)
	rm -f $(MAIN).run.xml $(MAIN).bbl $(MAIN).glo $(MAIN).ist $(MAIN).acn