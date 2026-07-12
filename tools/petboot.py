#!/usr/bin/env python3
"""Boot the converted PET build (build/pet.bin) under py65 and run a BASIC
session.  The REALIO=3 build calls the standard CBM KERNAL jump table
directly (verified address-for-address against a real PET KERNAL in
PORTING.md): CHROUT=$FFD2, CHRIN=$FFCF, GETIN=$FFE4, plus the channel-
management/STOP vectors, which are safe to stub as no-ops for a
single-channel console session.

Usage: petboot.py [script-file]   (default: a built-in smoke script)
"""
import sys
from py65.devices.mpu6502 import MPU

LOAD = 0xC000

# name -> (address, kind).  kind: 'out'=CHROUT, 'in'=CHRIN/GETIN, 'noop'=RTS,
# 'stop'=ISCNTC (return with carry clear -- STOP not pressed)
KERNAL = {
    'OPEN':   (0xFFC0, 'noop'),
    'CLOSE':  (0xFFC3, 'noop'),
    'CHKIN':  (0xFFC6, 'noop'),
    'CHKOUT': (0xFFC9, 'noop'),
    'CLRCH':  (0xFFCC, 'noop'),
    'CHRIN':  (0xFFCF, 'in'),
    'CHROUT': (0xFFD2, 'out'),
    'STOP':   (0xFFE1, 'stop'),
    'GETIN':  (0xFFE4, 'in'),
    'CLALL':  (0xFFE7, 'noop'),
}


def find_label(name):
    for line in open('build/pet.lbl'):
        parts = line.split()
        if len(parts) == 3 and parts[2] == '.' + name:
            return int(parts[1], 16)
    raise SystemExit(f'label {name} not found')


def main():
    image = open('build/pet.bin', 'rb').read()
    if len(sys.argv) > 1:
        text = open(sys.argv[1], newline='').read()  # keep literal \r, see kimboot.py
    else:
        text = ('PRINT 355/113\r'
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
    for addr, kind in KERNAL.values():
        m[addr] = 0x60  # RTS backstop; real behavior is trapped below
    mpu.pc = find_label('INIT')

    out = []
    trace = []
    steps = 0
    LIMIT = 60_000_000
    addr_kind = {addr: kind for addr, kind in KERNAL.values()}
    while steps < LIMIT:
        kind = addr_kind.get(mpu.pc)
        if kind is not None:
            if kind == 'out':
                out.append(mpu.a & 0x7F)
            elif kind == 'in':
                if not feed:
                    break  # script exhausted
                mpu.a = feed.pop(0)
                mpu.p &= ~0x02  # Z=0 (char available, GETIN convention)
            elif kind == 'stop':
                mpu.p &= ~0x01  # carry clear: STOP not pressed
            ret = m[0x101 + mpu.sp] | (m[0x102 + mpu.sp] << 8)
            mpu.sp = (mpu.sp + 2) & 0xFF
            mpu.pc = (ret + 1) & 0xFFFF
            continue
        if mpu.pc < 0x100 and m[mpu.pc] == 0x00:
            print(f'\n[hit BRK at ${mpu.pc:04X} after {steps} steps]')
            labels = {}
            for line in open('build/pet.lbl'):
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
