# Floppy mods

Procedure, rules and evidence: [`../MODDING_HOWTO.md`](../MODDING_HOWTO.md).
Loader facts: [`../notes/floppy_loader.md`](../notes/floppy_loader.md).
Builders read `07-rom/` and write only `build/mods/`.

| File | Role |
|------|------|
| `build_mod_sys.py` | Route A: patched Vailixi 3.50 relocated to RAM → `<NAME>.SYS`, `<NAME>.img` |
| `mod_stub.asm` | Route A stub: 3.50 BIOS guard, copy OS code + DGROUP, rejoin reset at `FAC0:0134` |
| `*.args` | One mod per file: `--name=` and `--patch=FILE:OLD:NEW` lines |
| `build_canary.py` | Route B minimal example: 288-byte `STARTUP.SYS` that prints `Vailixi 3.51 (---/--/----)` |

```bash
python3 mods/build_mod_sys.py @mods/DEMO351.args   # build/mods/DEMO351.{SYS,img}
python3 mods/build_canary.py                       # build/mods/STARTUP.SYS, vailixi350-canary.img
```

## Writing a real disk

The images are 2880-sector, 512-byte, 18-sector/track FAT12 (BIOS
geometry slot `F800:034F`). Copy the `.SYS` onto a freshly formatted
floppy, or write the whole image. On macOS, find the USB floppy with
`diskutil list` first:

```bash
diskutil unmountDisk /dev/diskN
sudo dd if=build/mods/DEMO351.img of=/dev/rdiskN bs=512
diskutil eject /dev/diskN
```

No mod has been booted on real hardware yet. Record what you see against
[`../MODDING_HOWTO.md`](../MODDING_HOWTO.md) §7–§8.
