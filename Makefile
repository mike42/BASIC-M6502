PY      = python3
CA65    = ca65
LD65    = ld65

BUILD   = build

all: kim pet apple osi

$(BUILD):
	mkdir -p $(BUILD)

# --- KIM (REALIO=1): compare against KB9, KIM BASIC V1.1 ---------------
# KB9 is the RAM-loaded tape build with long error messages, so it differs
# from the checked-in switch defaults: ROMSW=0, LNGERR=1.
KIMFLAGS = -D REALIO=1 -D ROMSW_OV=0 -D LNGERR=1

$(BUILD)/kim.o: $(BUILD) m6502.s src/macro10.inc
	$(CA65) -g -I src $(KIMFLAGS) -l $(BUILD)/kim.lst -o build/kim.o m6502.s

$(BUILD)/kim.bin: $(BUILD)/kim.o cfg/kim.cfg
	$(LD65) -C cfg/kim.cfg -o $@ -m $(BUILD)/kim.map \
	    --dbgfile $(BUILD)/kim.dbg -Ln $(BUILD)/kim.lbl $<

kim: $(BUILD)/kim.bin

# structural diff against the golden KB9 image (all differences are the
# documented 1977->1978 source evolution; see PORTING.md section 15)
diff-kim: $(BUILD)/kim.bin
	$(PY) tools/triage.py

# boot the build under py65 and run a BASIC session (needs py65:
# python3 -m venv .venv && .venv/bin/pip install py65)
PY65PY ?= $(PY)
run-kim: $(BUILD)/kim.bin
	$(PY65PY) tools/kimboot.py

# --- PET (REALIO=3): as shipped for the CBM KERNAL jump table -----------
PETFLAGS = -D REALIO=3

$(BUILD)/pet.o: $(BUILD) m6502.s src/macro10.inc
	$(CA65) -g -I src $(PETFLAGS) -l $(BUILD)/pet.lst -o build/pet.o m6502.s

$(BUILD)/pet.bin: $(BUILD)/pet.o cfg/pet.cfg
	$(LD65) -C cfg/pet.cfg -o $@ -m $(BUILD)/pet.map \
	    --dbgfile $(BUILD)/pet.dbg -Ln $(BUILD)/pet.lbl $<

pet: $(BUILD)/pet.bin

run-pet: $(BUILD)/pet.bin
	$(PY65PY) tools/petboot.py

# --- Apple II (REALIO=4): the source's own default, no -D needed --------
APPLEFLAGS = -D REALIO=4

$(BUILD)/apple.o: $(BUILD) m6502.s src/macro10.inc
	$(CA65) -g -I src $(APPLEFLAGS) -l $(BUILD)/apple.lst -o build/apple.o m6502.s

$(BUILD)/apple.bin: $(BUILD)/apple.o cfg/apple.cfg
	$(LD65) -C cfg/apple.cfg -o $@ -m $(BUILD)/apple.map \
	    --dbgfile $(BUILD)/apple.dbg -Ln $(BUILD)/apple.lbl $<

apple: $(BUILD)/apple.bin

run-apple: $(BUILD)/apple.bin
	$(PY65PY) tools/appleboot.py

# --- OSI (REALIO=2) ------------------------------------------------------
OSIFLAGS = -D REALIO=2

$(BUILD)/osi.o: $(BUILD) m6502.s src/macro10.inc
	$(CA65) -g -I src $(OSIFLAGS) -l $(BUILD)/osi.lst -o build/osi.o m6502.s

$(BUILD)/osi.bin: $(BUILD)/osi.o cfg/osi.cfg
	$(LD65) -C cfg/osi.cfg -o $@ -m $(BUILD)/osi.map \
	    --dbgfile $(BUILD)/osi.dbg -Ln $(BUILD)/osi.lbl $<

osi: $(BUILD)/osi.bin

run-osi: $(BUILD)/osi.bin
	$(PY65PY) tools/osiboot.py

clean:
	rm -rf $(BUILD)

.PHONY: all kim diff-kim run-kim pet run-pet apple run-apple osi run-osi clean
