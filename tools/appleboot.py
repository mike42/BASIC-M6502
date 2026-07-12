#!/usr/bin/env python3
"""Boot the converted Apple II build (build/apple.bin) under py65 and run a
BASIC session.  REALIO=4 uses two real Apple Monitor entry points (verified
against the source's own octal constants, see PORTING.md): COUT=$FDED (one
char out, A) and RDKEY=$FD0C (one raw char in, A, high bit set -- used both
directly and as CZGETL).

Line input (INLIN, m6502.asm ~1681) is trapped at the *program's own*
INLIN label instead of at the GETLN monitor call it makes internally
($FD67): GETLN's real 6502 register contract (what it returns in X to mean
"length") isn't independently documented here, and INLIN's own X-clamp
logic after the call turned out to depend on it in a way that's easy to
get subtly wrong (stale-buffer bugs on the second prompt). Synthesizing
INLIN's own well-defined contract with *its* caller instead sidesteps that:
fill BUF (the fixed $0200 monitor input buffer -- Apple's BUFPAG==2 config
makes BUF an alias for it, not a program-owned label, so it never appears
in apple.lbl) with the typed line and a 0 terminator, and return X,Y =
BUF-1, exactly like the real INLIN promises its callers.

Usage: appleboot.py [script-file]   (default: a built-in smoke script)
"""
import sys
from py65.devices.mpu6502 import MPU

LOAD = 0x0800
OUTCH = 0xFDED
RDKEY = 0xFD0C
BUF = 0x0200


def find_label(name):
    for line in open('build/apple.lbl'):
        parts = line.split()
        if len(parts) == 3 and parts[2] == '.' + name:
            return int(parts[1], 16)
    raise SystemExit(f'label {name} not found')


def main():
    image = open('build/apple.bin', 'rb').read()
    if len(sys.argv) > 1:
        text = open(sys.argv[1], newline='').read()  # keep literal \r, see kimboot.py
    else:
        text = ('24576\r'          # MEMORY SIZE?
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
    INLIN = find_label('INLIN')
    m[OUTCH] = 0x60
    m[RDKEY] = 0x60
    m[INLIN] = 0x60
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
        if mpu.pc == RDKEY:
            if not feed:
                break
            mpu.a = feed.pop(0) | 0x80  # RDKEY sets bit 7
            do_return()
            continue
        if mpu.pc == INLIN:
            if not feed:
                break
            n = 0
            while feed and feed[0] != ord('\r'):
                m[BUF + n] = feed.pop(0)  # no high bit -- INLIN already strips it
                n += 1
            if feed:
                feed.pop(0)  # consume the CR
            m[BUF + n] = 0  # terminator, like the real INLIN's "STA BUF,X"
            ptr = (BUF - 1) & 0xFFFF
            mpu.x = ptr & 0xFF
            mpu.y = (ptr >> 8) & 0xFF
            do_return()
            continue
        if mpu.pc < 0x100 and m[mpu.pc] == 0x00:
            print(f'\n[hit BRK at ${mpu.pc:04X} after {steps} steps]')
            labels = {}
            for line in open('build/apple.lbl'):
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
