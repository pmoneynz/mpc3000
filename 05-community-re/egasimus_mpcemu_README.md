# Akai MPC emulator

This is a NEC V53 emulator and disassembler to help me learn about assembly language
and binary reverse engineering techniques.

Right now, in `crates/v53/`, there's an implementation of about half the instruction set
of the NEC V53/V53A CPU used by AKAI devices. It goes as far as outputing the initial
boot text of the MPC3000 to a character display ("emulated" by printing those to the
console).

Eventually, I want to be able to run the Akai MPC OS in a box on my modern computer,
and perhaps augment the MPC2000XL OS (since there is no custom OS for that particular model.)

## Running

Place `mpc2000xl.bin` and/or `mpc3000-v3.12.bin` under `data/`
and run the corresponding command:

```
cargo run --example mpc2kxl
cargo run --example mpc3k
```

This will print a register/instruction trace of the OS ROM execution.

* [ ] TODO: proper CLI
* [ ] TODO: port to WASM, run in browser

## Obtaining OS ROMs

There are MPC60 and MPC3000 ROMs in MAME ROM collections, though you will
need to interleave those manually.

Alternatively, you can obtain the ROMs by dumping them from a real V53-based AKAI device,
or by googling for AKAI MPC firmware updates.
