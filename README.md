# Microsoft BASIC for 6502

This is Microsoft BASIC v1.1 for 6502 systems, adapted to build with the [ca65](https://github.com/cc65/cc65) assembler.

It is based on [the 2025 open source release of MS BASIC](https://github.com/microsoft/BASIC-M6502), which used the MACRO-10 assembler for the PDP-10. This repository tries to get it working on a modern 6502 assembler, so that anybody can build and boot the code.

See also [mist64/msbasic](https://github.com/mist64/msbasic/), which was an earlier project to reconstruct the source code from binaries that were released.

## Supported systems

Microsoft used conditional compilation to support for multiple systems:

- **MOS Technology KIM-1** (`REALIO=1`) - An influential single-board computer

There is also code for the following systems, but porting to ca65 has not yet been done:

- **Ohio Scientific (OSI)** (`REALIO=2`) - Popular among hobbyists and schools
- **Commodore PET** (`REALIO=3`) - One of the first complete personal computers
- **Apple II** (`REALIO=4`) - Steve Jobs and Steve Wozniak's revolutionary home computer

The **PDP-10 Simulation** (`REALIO=0`) is not able to be ported to a 6502 assembler, and will not work in this fork.

## Current status

This translation is machine-assisted: The original source code is being transformed from MACRO-10 to ca65 syntax via a large LLM-generated script at `tools/m10toca65.py`. The plan is to keep this until the 4 platforms are working, then switch this fork to build directly from a ca65-compatible assembly file.

## License

Microsoft BASIC v1.1 is copyright 1976-1978 (c) Microsoft Corporation, and was released in 2025 under the MIT License. See LICENSE for details.

