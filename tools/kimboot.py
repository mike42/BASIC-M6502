#!/usr/bin/env python3
"""Boot the converted KIM build (build/kim.bin) under py65 and run a BASIC
session.  KIM monitor I/O is trapped at the vector addresses the image
calls: OUTCH=$1EA0 (print char in A), GETCH=$1E5A (read char into A).

Usage: kimboot.py [script-file]   (default: a built-in smoke script)
"""
import sys
from py65.devices.mpu6502 import MPU

OUTCH = 0x1EA0
GETCH = 0x1E5A
LOAD = 0x2000

def find_label(name):
    for line in open('build/kim.lbl'):
        parts = line.split()
        if len(parts) == 3 and parts[2] == '.' + name:
            return int(parts[1], 16)
    raise SystemExit(f'label {name} not found')

def main():
    image = open('build/kim.bin', 'rb').read()
    if len(sys.argv) > 1:
        text = open(sys.argv[1]).read()
    else:
        text = ('24576\r'          # MEMORY SIZE?
                '72\r'             # TERMINAL WIDTH?
                'Y\r'              # WANT SIN-COS-TAN-ATN?
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
    zp = open('build/kim.zp', 'rb').read()  # page-zero initial image
    m[0:len(zp)] = list(zp)
    mpu.pc = find_label('INIT')
    # RTS as a backstop at the monitor vectors in case of a real jump
    m[OUTCH] = 0x60
    m[GETCH] = 0x60
    m[0x1740] = 0x80  # KIM TTY input port: line idle (no ^C pending)

    out = []
    trace = []
    steps = 0
    LIMIT = 60_000_000
    while steps < LIMIT:
        if mpu.pc == OUTCH:
            out.append(mpu.a & 0x7F)
            ret = m[0x101 + mpu.sp] | (m[0x102 + mpu.sp] << 8)
            mpu.sp = (mpu.sp + 2) & 0xFF
            mpu.pc = (ret + 1) & 0xFFFF
            continue
        if mpu.pc == GETCH:
            if not feed:
                break  # script exhausted
            mpu.a = feed.pop(0)
            ret = m[0x101 + mpu.sp] | (m[0x102 + mpu.sp] << 8)
            mpu.sp = (mpu.sp + 2) & 0xFF
            mpu.pc = (ret + 1) & 0xFFFF
            continue
        if mpu.pc < 0x100 and m[mpu.pc] == 0x00:
            print(f'\n[hit BRK at ${mpu.pc:04X} after {steps} steps]')
            labels = {}
            for line in open('build/kim.lbl'):
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
