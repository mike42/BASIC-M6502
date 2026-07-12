#!/usr/bin/env python3
"""Boot the converted OSI build (build/osi.bin) under py65 and run a BASIC
session.  REALIO=2 output is a real monitor call, OUTCH=$FE0B, but *input*
is inlined hardware: INCHR (m6502.asm ~1745) busy-polls a 6850-style ACIA
directly at $FC00 (status)/$FC01 (data) rather than calling a monitor
vector -- there is no single address to trap the way KIM/PET/Apple's
GETCH/CHRIN/RDKEY calls allow.

Rather than emulate the ACIA registers (and the "REPEAT 4,<NOP>" timing
padding around them), this traps the program's own INCHR *label* -- the
whole poll-and-mask routine -- and synthesizes its net effect: pop one
character off the feed queue into A, RTS.  Every OSI call site (line
input, and ISCNTC's own inline "JSR INCHR" to eat a pending Control-C)
goes through this one routine, so trapping the label is equivalent to
trapping the two registers, without needing their read/write protocol.

Usage: osiboot.py [script-file]   (default: a built-in smoke script)
"""
import sys
from py65.devices.mpu6502 import MPU

LOAD = 0x2000
OUTCH = 0xFE0B


def find_label(name):
    for line in open('build/osi.lbl'):
        parts = line.split()
        if len(parts) == 3 and parts[2] == '.' + name:
            return int(parts[1], 16)
    raise SystemExit(f'label {name} not found')


def main():
    image = open('build/osi.bin', 'rb').read()
    if len(sys.argv) > 1:
        text = open(sys.argv[1], newline='').read()  # keep literal \r, see kimboot.py
    else:
        text = ('40000\r'          # MEMORY SIZE? (must be > RAMLOC=$8000=32768:
                                    # OSI's ROM build puts variable storage
                                    # high, unlike KIM/Apple's low RAMLOC)
                '72\r'             # TERMINAL WIDTH?
                'PRINT 355/113\r'
                'A$="HELLO"+" WORLD":PRINT LEN(A$);A$\r'
                'FOR I=1TO5:PRINT I*I;:NEXT:PRINT\r'
                '10 FOR J=1 TO 3\r'
                '20 PRINT J;SQR(J)\r'
                '30 NEXT J\r'
                'LIST\r'
                'RUN\r'
                'PRINT FRE(0)\r'
                'PRINT "BYE"\r')
    feed = [ord(c) for c in text]

    mpu = MPU()
    m = mpu.memory
    m[LOAD:LOAD + len(image)] = list(image)
    INCHR = find_label('INCHR')
    m[OUTCH] = 0x60
    m[INCHR] = 0x60
    mpu.pc = find_label('INIT')

    def do_return():
        ret = m[0x101 + mpu.sp] | (m[0x102 + mpu.sp] << 8)
        mpu.sp = (mpu.sp + 2) & 0xFF
        mpu.pc = (ret + 1) & 0xFFFF

    out = []
    trace = []
    steps = 0
    LIMIT = 60_000_000
    while steps < LIMIT:
        if mpu.pc == OUTCH:
            out.append(mpu.a & 0x7F)
            do_return()
            continue
        if mpu.pc == INCHR:
            if not feed:
                break
            mpu.a = feed.pop(0)
            do_return()
            continue
        if mpu.pc < 0x100 and m[mpu.pc] == 0x00:
            print(f'\n[hit BRK at ${mpu.pc:04X} after {steps} steps]')
            labels = {}
            for line in open('build/osi.lbl'):
                p = line.split()
                if len(p) == 3:
                    labels[int(p[1], 16)] = p[2][1:]
            for pc in trace[-30:]:
                near = max((a for a in labels if a <= pc), default=0)
                print(f'  ${pc:04X}  {labels.get(near,"?")}+{pc-near}')
            break
        trace.append(mpu.pc)
        mpu.step()
        steps += 1
    else:
        print(f'\n[step limit reached at PC=${mpu.pc:04X}]')

    sys.stdout.write(''.join(chr(c) for c in out if c not in (0,)))
    print(f'\n[{steps} steps executed]')


if __name__ == '__main__':
    main()
