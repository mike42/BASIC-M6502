PY      = python3
CA65    = ca65
LD65    = ld65

BUILD   = build

all: kim

$(BUILD):
	mkdir -p $(BUILD)

# --- conversion -------------------------------------------------------
$(BUILD)/m6502_ca65.s: m6502.asm tools/m10toca65.py | $(BUILD)
	$(PY) tools/m10toca65.py m6502.asm -o $@ --linemap $(BUILD)/linemap.txt

# --- KIM (REALIO=1): compare against KB9, KIM BASIC V1.1 ---------------
# KB9 is the RAM-loaded tape build with long error messages, so it differs
# from the checked-in switch defaults: ROMSW=0, LNGERR=1.
KIMFLAGS = -D REALIO=1 -D ROMSW_OV=0 -D LNGERR=1

$(BUILD)/kim.o: $(BUILD)/m6502_ca65.s src/macro10.inc
	$(CA65) -g -I src $(KIMFLAGS) -l $(BUILD)/kim.lst -o $@ $<

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

clean:
	rm -rf $(BUILD)

.PHONY: all kim diff-kim run-kim clean
