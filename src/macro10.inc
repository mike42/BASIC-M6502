; macro10.inc -- reconstructed contract of the missing M6502.UNV universal
; file, reduced to what m6502.asm actually uses.  The addressing-mode
; pseudo-mnemonics (LDAI, LDADY, JMPD, ...) are rewritten to native ca65
; syntax by tools/m10toca65.py and do not appear here.

; ADR(x) -- emit a little-endian address word.
.macro	ADR addr
	.word	addr
.endmacro

; DC(str) -- ASCII text with bit 7 set on the final character.  Used via
; DCI (reserved-word/crunch list) and DCE (error-message table); CRUNCH
; detects the end of a keyword by the sign bit.
.macro	DC str
	.repeat	.strlen(str)-1, i
	.byte	.strat(str, i)
	.endrepeat
	.byte	.strat(str, .strlen(str)-1) | $80
.endmacro
