#!/usr/bin/env python3
"""Mechanical MACRO-10 -> ca65 converter for m6502.asm (Microsoft BASIC 6502 v1.1).

Not a general MACRO-10 translator: it implements exactly the constructs the
BASIC source uses (see PORTING.md sections 4-6 and 8). Structure:

  pre-scan  - collect DEFINE'd macro names; count symbol assignments to decide
              '=' (single assignment, lazy) vs '.set' (reassigned / snapshots
              of .set symbols, immediate)
  main pass - line-oriented parser with a bracket stack spanning lines.
              Bracket kinds: conditional bodies (.if/.endif), macro definition
              bodies (.macro/.endmacro), repeat bodies (.repeat/.endrepeat),
              discarded bodies (REALIO=0 / IF2), transparent bodies (IF1),
              and expression grouping (<> -> parens, handled inside xexpr).

The REALIO=0 (PDP-10 simulator) target contains PDP-10 host instructions and
is punched out: block bodies are emitted as ';X' comments.

Outputs the converted source and a linemap ("outline\tsrcline") for
source-correlation tests.
"""
import argparse
import re
import sys

# --------------------------------------------------------------------------
# tables

MNEMONICS = set("""
ADC AND ASL BCC BCS BEQ BIT BMI BNE BPL BRK BVC BVS CLC CLD CLI CLV CMP CPX
CPY DEC DEX DEY EOR INC INX INY JMP JSR LDA LDX LDY LSR NOP ORA PHA PHP PLA
PLP ROL ROR RTI RTS SBC SEC SED SEI STA STX STY TAX TAY TSX TXA TXS TYA
""".split())

# addressing-mode pseudo-mnemonics from the (missing) M6502.UNV
PSEUDO_IMM = {
    'LDAI': 'LDA', 'LDXI': 'LDX', 'LDYI': 'LDY', 'CMPI': 'CMP',
    'CPXI': 'CPX', 'CPYI': 'CPY', 'ADCI': 'ADC', 'SBCI': 'SBC',
    'ANDI': 'AND', 'ORAI': 'ORA', 'EORI': 'EOR',
}
PSEUDO_INDY = {
    'LDADY': 'LDA', 'STADY': 'STA', 'CMPDY': 'CMP',
    'ADCDY': 'ADC', 'SBCDY': 'SBC',
}
PSEUDO_IND = {'JMPD': 'JMP'}

# macros whose operand is a string literal to pass through untouched
DATA_MACROS = {'DT', 'DCI', 'DCE', 'DC'}

# provided by macro10.inc
INC_MACROS = {'ADR', 'DC'}

# ORG -> segment switch + absolute .org (org_per_seg).  Absolute addressing
# keeps the source's address-dependent conditionals (buffer page-crossing
# checks) and zero-page operand sizing working.  ORG 80 (Apple, inside a
# conditional) stays within the ZP segment as a bare .org, like the original.
ORG_SEGMENTS = {'0': 'ZP', '255': 'ST01', 'ROMLOC': 'CODE'}

LISTING_DIRECTIVES = {'PAGE', 'SALL', 'XLIST', '.XCREF', '.CREF', 'PURGE',
                      'TITLE', 'LIST'}

IDENT = re.compile(r'[A-Z0-9$.%]+')
LABEL_RE = re.compile(r'([A-Z0-9$.]+)(::|:!|:)')


def trunc6(tok):
    """MACRO-10 symbols are significant to six characters (manual 2.2.2):
    RESTORE and RESTOR name the same symbol."""
    return tok[:6]

# exact-line replacements, keyed by 1-based line number; each entry is
# (expected-substring, [replacement lines]).  A mismatch aborts: it means
# m6502.asm changed and the table must be reviewed.
LITERAL = {
    2: ('SEARCH', ['\t.include "macro10.inc" ;[was: SEARCH M6502]']),
    6: ('$Z::', [';[removed] $Z:: (PDP-10 simulator start label)']),
    10: ('REALIO=4', ['.ifndef REALIO ;[REALIO selectable via ca65 -D REALIO=n]',
                      'REALIO = 4',
                      '.endif']),
    # DEFINE DT(Q),< IRPC Q,<IFDIF <Q><">,<EXP "Q">>>  -- quote-stripping
    # loop; ca65 .byte takes the string directly.
    123: ('DEFINE\tDT(Q)', ['.macro\tDT STR ;[was: IRPC quote-stripping loop]',
                            '\t.byte\tSTR',
                            '.endmacro']),
    124: ('IRPC', []),
    # DEFINE INCW(R) uses a MACRO-10 generated symbol %Q -> .local
    183: ('DEFINE\tINCW(R)', ['.macro\tINCW R ;[%Q generated symbol -> .local]',
                              '\t.local\tINCWSKP',
                              '\tINC\tR',
                              '\tBNE\tINCWSKP',
                              '\tINC\tR+1',
                              'INCWSKP:',
                              '.endmacro']),
    184: ('INC\tR', []),
    185: ('BNE\t%Q', []),
    186: ('INC\tR+1', []),
    187: ('%Q:>', []),
    6955: ('END\t$Z+START', [';[removed] END $Z+START (entry point is the load address)']),
    # Upstream gap: the REALIO=2 (OSI) switch block never assigns CZGETL, the
    # single-raw-character "GET" entry point every other target defines
    # (see line 3310's "JSR CZGETL", unconditional across all REALIO
    # values).  This means the master source alone cannot build a working
    # OSI target -- some further OEM-specific patch, lost to history, must
    # have supplied it for the real ROM burn (same story as ROMLOC, which
    # this branch also never touches; see cfg/osi.cfg).  Alias it to this
    # file's own OSI single-character poll routine (INCHR's REALIO-2 body,
    # ~line 1745) rather than inventing a hardware address from scratch.
    88: ('OUTCH==^O177013>', ['\tOUTCH = $FE0B',
                              '\tCZGETL = INCHR ;[PATCH: OSI never defines CZGETL, see PORTING.md]',
                              '.endif']),
    # Upstream bug in the 1978 source: STXY TXTTAB was moved inside
    # IFN ROMSW, so RAM builds (ROMSW=0, e.g. the KB9-style KIM tape
    # build) never initialize TXTTAB and INIT crashes.  The 1977 KB9
    # binary stores TXTTAB unconditionally here; restore that.  All
    # ROM builds are byte-identical either way.
    6873: ('IFN\tROMSW,<', ['.if (ROMSW) <> 0 ;[PATCH: STXY TXTTAB made unconditional, see PORTING.md]']),
    6874: ('LDXYI\tRAMLOC', ['\tLDXYI\tRAMLOC']),
    6875: ('STXY\tTXTTAB>', ['.endif',
                             '\tSTXY\tTXTTAB']),
}


class Bracket:
    COND = 'cond'          # IFE/IFN/IFNDEF -> .endif
    MACRO = 'macro'        # DEFINE -> .endmacro
    REPEAT = 'repeat'      # REPEAT -> .endrepeat
    DISCARD = 'discard'    # REALIO=0 body / IF2 -> nothing (';X' comments)
    TRANSPARENT = 'transp' # IF1 -> nothing (body kept)

    def __init__(self, kind, renames=None):
        self.kind = kind
        self.renames = renames or {}


class Converter:
    def __init__(self, lines):
        self.lines = lines
        self.out = []            # output lines
        self.linemap = []        # (out_lineno, src_lineno)
        self.warnings = []
        self.radix = 8           # MACRO-10 default until RADIX 10 at line 4
        self.stack = []
        self.comment_delim = None
        self.srcline = 0
        self.macros = set(INC_MACROS) | {'DT', 'INCW'}
        self.set_syms = set()
        self.assigned = set()
        self.seen_set = set()
        self.prescan()

    # ---------------------------------------------------------- pre-scan
    def prescan(self):
        assign_re = re.compile(r'(?<![A-Z0-9$.])([A-Z0-9$.]+)\s*==?(?![=:])')
        counts = {}
        rhs = {}
        cdelim = None  # inside COMMENT block?
        for raw in self.lines:
            code = split_comment(strip_strings(raw.upper()))[0]
            if cdelim is not None:
                if cdelim in raw:
                    cdelim = None
                continue
            m = re.match(r'\s*COMMENT\s*(\S)', code)
            if m:
                if code.count(m.group(1)) < 2:
                    cdelim = m.group(1)
                continue
            m = re.match(r'\s*DEFINE\s+([A-Z0-9$.]+)', code)
            if m:
                self.macros.add(trunc6(m.group(1)))
            for m in assign_re.finditer(code):
                sym = trunc6(m.group(1))
                if sym in ('REALIO',):  # literal-replaced; stays '='
                    continue
                counts[sym] = counts.get(sym, 0) + 1
                rest = code[m.end():]
                rhs.setdefault(sym, []).append(rest)
        self.assigned = set(counts)
        multi = {s for s, n in counts.items() if n > 1}
        # a symbol whose RHS mentions a label (a non-assigned identifier)
        # cannot be .set (needs a constant); demote to '=' -- only correct
        # when its assignments are in mutually exclusive branches.
        for sym in sorted(multi):
            for r in rhs[sym]:
                r = re.sub(r'\^[ODB][0-9]+', '', r)  # radix escapes
                idents = [t for t in map(trunc6, IDENT.findall(r))
                          if not t.isdigit() and t not in self.assigned]
                if idents:
                    multi.discard(sym)
                    self.warnings.append(
                        f'{sym}: multi-assigned label alias (refs '
                        f'{idents}); using "=" - branches must be exclusive')
                    break
        # fixpoint: single-assigned symbols whose RHS mentions a .set symbol
        # must snapshot immediately -> also .set
        changed = True
        while changed:
            changed = False
            for sym, rlist in rhs.items():
                if sym in multi:
                    continue
                for r in rlist:
                    toks = set(map(trunc6, IDENT.findall(r)))
                    if toks & multi:
                        multi.add(sym)
                        changed = True
                        break
        self.set_syms = multi

    # ---------------------------------------------------------- helpers
    def emit(self, text, src=None):
        self.out.append(text)
        self.linemap.append((len(self.out), src or self.srcline))

    def warn(self, msg):
        self.warnings.append(f'{self.srcline}: {msg}')

    # ---------------------------------------------------------- numbers
    def number(self, tok):
        """Convert a bare number token per current radix.  Manual 2.2.1:
        a single-digit number is always decimal, whatever the radix."""
        if self.radix == 8 and len(tok) > 1:
            val = int(tok, 8)
            return str(val) if val < 8 else f'${val:X}'
        return tok

    # ---------------------------------------------------------- expressions
    def xexpr(self, s, pos, stop_comma=False, raw=False):
        """Translate an expression starting at pos.  Returns (text, newpos).
        Stops at an unmatched '>' (body closer), end of string, or a
        top-level comma when stop_comma.  raw=True passes text through
        (string operands of data macros)."""
        outp = []
        depth = 0
        n = len(s)
        while pos < n:
            c = s[pos]
            if c == '"':
                end = s.find('"', pos + 1)
                if end < 0:
                    self.warn('unterminated string')
                    end = n - 1
                lit = s[pos:end + 1]
                if raw:
                    outp.append(lit)
                else:
                    inner = lit[1:-1]
                    if len(inner) == 1:
                        outp.append("'" + inner + "'")
                    else:
                        self.warn(f'multi-char string in expression: {lit}')
                        outp.append(lit)
                pos = end + 1
                continue
            if c == '<' and not raw:
                depth += 1
                outp.append('(')
                pos += 1
                continue
            if c == '>':
                if depth > 0 and not raw:
                    depth -= 1
                    outp.append(')')
                    pos += 1
                    continue
                break  # body closer -- caller handles
            if c == ',' and depth == 0 and stop_comma:
                break
            if c == '!' and not raw:
                outp.append('|')  # MACRO-10 inclusive OR
                pos += 1
                continue
            if c == '^' and not raw:
                m = re.match(r'\^O([0-7]+)|\^D([0-9]+)|\^B([01]+)', s[pos:])
                if m:
                    if m.group(1) is not None:
                        outp.append(f'${int(m.group(1), 8):X}')
                    elif m.group(2) is not None:
                        outp.append(m.group(2))
                    else:
                        outp.append('%' + m.group(3))
                    pos += m.end()
                    continue
                self.warn(f'unhandled ^ escape: {s[pos:pos+4]}')
                outp.append(c)
                pos += 1
                continue
            if c == '.' and not raw:
                nxt = s[pos + 1] if pos + 1 < n else ''
                prev = outp[-1][-1] if outp and outp[-1] else ''
                if nxt in '+-' and not (prev.isalnum() or prev in '$.'):
                    outp.append('*')  # current PC
                    pos += 1
                    continue
            m = IDENT.match(s, pos)
            if m:
                tok = m.group(0)
                if raw:
                    # data-macro operand: no transforms, but macro-parameter
                    # renames still apply (DC(A) inside DCI's body)
                    outp.append(self.rename(trunc6(tok)))
                elif tok.isdigit():
                    outp.append(self.number(tok))
                else:
                    outp.append(self.rename(trunc6(tok)))
                pos = m.end()
                continue
            outp.append(c)
            pos += 1
        text = ''.join(outp).strip()
        while text.endswith(','):  # stray trailing commas (line 6734)
            text = text[:-1].rstrip()
        return text, pos

    # ---------------------------------------------------------- statements
    def close_bracket(self):
        br = self.stack.pop()
        if br.kind == Bracket.COND:
            self.emit('.endif')
        elif br.kind == Bracket.MACRO:
            self.emit('.endmacro')
        elif br.kind == Bracket.REPEAT:
            self.emit('.endrepeat')
        elif br.kind == Bracket.DISCARD:
            self.emit(';X [end of removed block]')
        # TRANSPARENT: nothing

    def in_discard(self):
        return any(b.kind == Bracket.DISCARD for b in self.stack)

    def rename(self, tok):
        """Apply macro-parameter renames of enclosing macro definitions."""
        for br in reversed(self.stack):
            if br.kind == Bracket.MACRO and tok in br.renames:
                return br.renames[tok]
        return tok

    def open_body(self, s, pos, bracket):
        """Expect '<' at/after pos, push bracket, return new pos."""
        while pos < len(s) and s[pos] in ' \t':
            pos += 1
        if pos < len(s) and s[pos] == '<':
            self.stack.append(bracket)
            return pos + 1
        self.warn(f'expected < for body, got: {s[pos:pos+10]!r}')
        self.stack.append(bracket)
        return pos

    def do_discard_text(self, s, pos, comment):
        """Consume text inside a discarded body: track brackets only."""
        start = pos
        while pos < len(s):
            c = s[pos]
            if c == '"':
                end = s.find('"', pos + 1)
                pos = (end if end >= 0 else len(s) - 1) + 1
                continue
            if c == '<':
                self.stack.append(Bracket(Bracket.DISCARD))
                pos += 1
                continue
            if c == '>':
                consumed = s[start:pos]
                if consumed.strip():
                    self.emit(';X ' + consumed.strip())
                self.close_bracket()
                return pos + 1
            pos += 1
        text = s[start:].strip()
        if text or comment:
            self.emit(';X ' + text + (('\t;' + comment) if comment else ''))
        return pos

    def statements(self, s, pos, comment):
        """Parse statements in s from pos until exhausted."""
        first = True
        while True:
            while pos < len(s) and s[pos] in ' \t':
                pos += 1
            if pos >= len(s):
                if first and comment and not self.in_discard():
                    self.emit(';' + comment)
                return
            if self.in_discard():
                pos = self.do_discard_text(s, pos, comment if first else '')
                first = False
                continue
            if s[pos] == '>':
                self.close_bracket()
                pos += 1
                continue
            pos = self.statement(s, pos, comment if first else '')
            first = False

    def statement(self, s, pos, comment):
        tail = ('\t;' + comment) if comment else ''
        # labels
        labels = []
        while True:
            m = LABEL_RE.match(s, pos)
            if not m:
                break
            labels.append(trunc6(m.group(1)))
            pos = m.end()
            while pos < len(s) and s[pos] in ' \t':
                pos += 1
        label_prefix = ''.join(lbl + ':' for lbl in labels)
        if pos >= len(s) or s[pos] == '>':
            if label_prefix:
                self.emit(label_prefix + tail)
            elif comment:
                self.emit(';' + comment)
            return pos

        def out(text):
            self.emit((label_prefix + '\t' if label_prefix else '\t') + text + tail)

        m = IDENT.match(s, pos)
        if not m:
            # bare punctuation-led expression? treat as data
            expr, pos2 = self.xexpr(s, pos)
            out('.byte\t' + expr)
            return pos2
        op = m.group(0)
        after = m.end()

        # assignment?
        m2 = re.match(r'\s*(==?)(?![=:])', s[after:])
        if m2:
            expr, pos2 = self.xexpr(s, after + m2.end())
            sym = trunc6(op)
            # configuration switches (top level, head of file) become
            # overridable from the ca65 command line: plain symbols via
            # -D SYM=n, .set variables via -D SYM_OV=n (applied at their
            # first assignment)
            config = not self.stack and self.srcline < 110
            if sym in self.set_syms:
                if config and sym not in self.seen_set:
                    self.seen_set.add(sym)
                    out(f'.ifdef {sym}_OV')
                    self.emit(f'{sym} .set {sym}_OV')
                    self.emit('.else')
                    self.emit(f'{sym} .set {expr}')
                    self.emit('.endif')
                else:
                    out(f'{sym} .set {expr}')
            else:
                if config:
                    out(f'.ifndef {sym}')
                    self.emit(f'{sym} = {expr}')
                    self.emit('.endif')
                else:
                    out(f'{sym} = {expr}')
            return pos2

        pos = after

        # conditionals ------------------------------------------------
        if op in ('IFE', 'IFN'):
            cond, pos = self.xexpr(s, pos, stop_comma=True)
            if pos < len(s) and s[pos] == ',':
                pos += 1
            if op == 'IFE' and cond == 'REALIO':
                self.emit(';X [REALIO=0 (PDP-10 simulator) block removed]' + tail)
                return self.open_body(s, pos, Bracket(Bracket.DISCARD))
            rel = '=' if op == 'IFE' else '<>'
            out(f'.if ({cond}) {rel} 0')
            return self.open_body(s, pos, Bracket(Bracket.COND))
        if op in ('IFDEF', 'IFNDEF'):
            sym, pos = self.xexpr(s, pos, stop_comma=True)
            if pos < len(s) and s[pos] == ',':
                pos += 1
            out(('.ifdef ' if op == 'IFDEF' else '.ifndef ') + sym)
            return self.open_body(s, pos, Bracket(Bracket.COND))
        if op == 'IF1':
            if pos < len(s) and s[pos] == ',':
                pos += 1
            if comment:
                self.emit(';' + comment)
            return self.open_body(s, pos, Bracket(Bracket.TRANSPARENT))
        if op == 'IF2':
            if pos < len(s) and s[pos] == ',':
                pos += 1
            self.emit(';X [IF2 (pass-2 only) block removed]' + tail)
            return self.open_body(s, pos, Bracket(Bracket.DISCARD))

        # macro definition --------------------------------------------
        if op == 'DEFINE':
            m3 = re.match(r'\s*([A-Z0-9$.]+)\s*(?:\(([A-Z0-9$.,\s]*)\))?\s*,?', s[pos:])
            if not m3:
                self.warn('unparsable DEFINE')
                out('; ' + s[pos:])
                return len(s)
            name = m3.group(1)
            args = (m3.group(2) or '').replace(',', ' ').split()
            pos += m3.end()
            self.macros.add(name)
            # A/X/Y are register keywords in ca65; rename such parameters
            renames = {a: 'P' + a for a in args if a in ('A', 'X', 'Y')}
            args = [renames.get(a, a) for a in args]
            out('.macro\t' + name + ((' ' + ', '.join(args)) if args else ''))
            return self.open_body(s, pos, Bracket(Bracket.MACRO, renames))

        if op == 'REPEAT':
            cnt, pos = self.xexpr(s, pos, stop_comma=True)
            if pos < len(s) and s[pos] == ',':
                pos += 1
            out('.repeat ' + cnt)
            return self.open_body(s, pos, Bracket(Bracket.REPEAT))

        # simple directives -------------------------------------------
        if op == 'RADIX':
            m3 = re.match(r'\s*([0-9]+)', s[pos:])
            self.radix = int(m3.group(1))  # RADIX arg is always decimal
            out(f'; RADIX {self.radix} [literals converted by m10toca65]')
            return pos + m3.end()
        if op == 'ORG':
            arg, pos = self.xexpr(s, pos)
            seg = ORG_SEGMENTS.get(arg)
            if seg is None:
                out(f'.org\t{arg}')
            else:
                out(f'.segment "{seg}"')
                self.emit(f'\t.org\t{arg}')
            return pos
        if op == 'COMMENT':
            rest = s[pos:].strip()
            if not rest:
                self.warn('COMMENT with no delimiter')
                return len(s)
            delim = rest[0]
            body = rest[1:]
            end = body.find(delim)
            if end >= 0:
                self.emit(';' + body[:end])
                return pos + 2 + end
            self.comment_delim = delim
            self.emit(';' + body)
            return len(s)
        if op == 'PRINTX':
            # message runs to EOL or an enclosing body's '>' closer
            end = s.find('>', pos)
            if end < 0:
                end = len(s)
            rest = s[pos:end].strip()
            if rest and not (rest[0].isalnum() or rest[0] in ' \t'):
                d = rest[0]
                rest = rest[1:].rstrip(d)
            out(f'.out "{rest.strip()}"')
            return end
        if op == 'SUBTTL':
            self.emit(';;; ----- ' + s[pos:].strip() + ' -----' + tail)
            return len(s)
        if op in LISTING_DIRECTIVES:
            self.emit('; ' + (label_prefix + ' ' if label_prefix else '') + op + ' ' + s[pos:].strip())
            return len(s)
        if op == 'BLOCK':
            expr, pos = self.xexpr(s, pos)
            out('.res\t' + expr)
            return pos
        if op == 'EXP':
            expr, pos = self.xexpr(s, pos)
            out('.byte\t' + expr)
            return pos
        if op == 'XWD':
            left, pos = self.xexpr(s, pos, stop_comma=True)
            if pos < len(s) and s[pos] == ',':
                pos += 1
            right, pos = self.xexpr(s, pos)
            out(f'.byte\t{right} ;[was: XWD {left},{right} - low byte only]')
            return pos
        if op == 'END':
            out('; END ' + s[pos:].strip())
            return len(s)

        # pseudo-mnemonics ---------------------------------------------
        if op in PSEUDO_IMM:
            expr, pos = self.xexpr(s, pos)
            # MACRO-10 packs the immediate into one byte at word->byte time,
            # silently truncating (e.g. <BUF&255>-1 = -1 -> 255 when BUF is
            # page-aligned, m6502.asm:1863).  ca65 requires #-operands to be
            # in [0,255] and won't auto-wrap, so force the low byte.
            out(f'{PSEUDO_IMM[op]}\t#<({expr})')
            return pos
        if op in PSEUDO_INDY:
            expr, pos = self.xexpr(s, pos)
            out(f'{PSEUDO_INDY[op]}\t({expr}),Y')
            return pos
        if op in PSEUDO_IND:
            expr, pos = self.xexpr(s, pos)
            out(f'{PSEUDO_IND[op]}\t({expr})')
            return pos

        # real mnemonics ------------------------------------------------
        if op in MNEMONICS:
            expr, pos = self.xexpr(s, pos)
            if expr.startswith('('):
                # converted <>-grouping; the source never writes ()-indirect
                # (it used JMPD/..DY pseudo-mnemonics), so force non-indirect
                if balanced_whole(expr):
                    expr = expr[1:-1]
                else:
                    expr = '+' + expr
            out(op + ('\t' + expr if expr else ''))
            return pos

        # macro calls ---------------------------------------------------
        if op in self.macros:
            israw = op in DATA_MACROS
            expr, pos = self.xexpr(s, pos, raw=israw)
            if expr.startswith('(') and balanced_whole(expr):
                expr = expr[1:-1]  # NAME(ARG) call form
            out(op + ('\t' + expr if expr else ''))
            return pos

        # bare data expression: a number, or a value symbol (LINWID: LINLEN)
        if op.isdigit() or op.replace('.', '').isdigit() or op in self.assigned:
            # re-parse from the token start as an expression
            expr, pos = self.xexpr(s, pos - len(op))
            out('.byte\t' + expr)
            return pos

        self.warn(f'unknown op {op!r}; passed through')
        expr, pos = self.xexpr(s, pos)
        out(op + ('\t' + expr if expr else ''))
        return pos

    # ---------------------------------------------------------- main loop
    def convert(self):
        self.emit('; Generated from m6502.asm by tools/m10toca65.py -- do not edit.')
        self.emit('; Build: ca65 -D REALIO=1 (KIM) etc.; see PORTING.md.')
        self.emit('.feature ubiquitous_idents ; RORSW=0 defines a macro named ROR')
        self.emit('.feature org_per_seg ; segments are absolute (see ORG handling)')
        self.emit('')
        for i, raw in enumerate(self.lines, 1):
            self.srcline = i
            line = raw.rstrip('\n').replace('\f', '')
            if i in LITERAL:
                expect, repl = LITERAL[i]
                if expect not in line:
                    sys.exit(f'line {i}: expected {expect!r} for literal '
                             f'replacement, got: {line!r}')
                for t in repl:
                    self.emit(t)
                continue
            if self.comment_delim is not None:
                d = self.comment_delim
                if d in line:
                    self.comment_delim = None
                    self.emit(';' + line[:line.index(d)])
                else:
                    self.emit(';' + line)
                continue
            code, comment = split_comment(line)
            code = upcase_outside_strings(code)
            if not code.strip():
                self.emit(';' + comment if comment else '')
                continue
            self.statements(code, 0, comment)
        if self.stack:
            self.warn(f'unclosed brackets at EOF: '
                      f'{[b.kind for b in self.stack]}')
        return self.out


# --------------------------------------------------------------------------
def split_comment(line):
    """Split at first ';' outside double quotes."""
    inq = False
    for i, c in enumerate(line):
        if c == '"':
            inq = not inq
        elif c == ';' and not inq:
            return line[:i], line[i + 1:]
    return line, ''


def strip_strings(s):
    return re.sub(r'"[^"]*"', '""', s)


def upcase_outside_strings(s):
    parts = re.split(r'("[^"]*")', s)
    return ''.join(p if p.startswith('"') else p.upper() for p in parts)


def balanced_whole(expr):
    """True if expr is entirely wrapped by one paren pair."""
    if not (expr.startswith('(') and expr.endswith(')')):
        return False
    depth = 0
    for i, c in enumerate(expr):
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i == len(expr) - 1
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--linemap')
    args = ap.parse_args()
    with open(args.input, 'r', encoding='latin-1') as f:
        lines = f.readlines()
    conv = Converter(lines)
    out = conv.convert()
    with open(args.output, 'w') as f:
        f.write('\n'.join(out) + '\n')
    if args.linemap:
        with open(args.linemap, 'w') as f:
            for outno, srcno in conv.linemap:
                f.write(f'{outno}\t{srcno}\n')
    for w in conv.warnings:
        print('warning:', w, file=sys.stderr)
    print(f'{len(out)} lines written, {len(conv.warnings)} warnings',
          file=sys.stderr)


if __name__ == '__main__':
    main()
