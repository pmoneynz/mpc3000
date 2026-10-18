# Notes

- [Waveform playback](wave_playback.md): stock audition ABI and pad-dispatch boundary.

Load-bearing analysis for Vailixi OS 3.50. New notes must close a named
uncertainty or correct a proven error. Status of the project:
[`../STATUS.md`](../STATUS.md).

| Note | Role |
|------|------|
| [`rom_compatibility.md`](rom_compatibility.md) | Physical personalized 3.50 guard rejection and ROM comparison diagnostic |
| [`waveform_bench.md`](waveform_bench.md) | First physical canary result, waveform review, bench image and procedure |
| [`waveform_engine.md`](waveform_engine.md) | Help-on-Edit-Sound waveform feature, point editing, zoom and stereo planes |
| [`mute_groups.md`](mute_groups.md) | BENCH 06 controls, menu hooks, UI execution evidence |
| [`mute_voice.md`](mute_voice.md) | Shared note-on/voice allocator hooks and group choking |
| [`mute_storage.md`](mute_storage.md) | Program state lifetime and PGM/APS extensions |
| [`lazy_chop.md`](lazy_chop.md) | Lazy Chop on 3.16: pad ownership, the take, CHOPS refine, Convert (spec and as built) |
| [`artifact_identity.md`](artifact_identity.md) | What the bytes are |
| [`address_model.md`](address_model.md) | How those bytes are addressed |
| [`boot_reset_to_bios_banner.md`](boot_reset_to_bios_banner.md) | First connected slice |
| [`amx_wait.md`](amx_wait.md) | AMX TCB select / idle condition |
| [`amx_first_dispatch.md`](amx_first_dispatch.md) | First `01EA` creates task 6 |
| [`int43_ax4.md`](int43_ax4.md) | Banner character → LC7981 ports |
| [`front_panel.md`](front_panel.md) | D19 PARTIAL: panel ROM absent; `0xC0-0xDF` I/O only |
| [`pgr61.md`](pgr61.md) | P7/P8: page 61 word `0x0140` → `0x500000`; consumer `D9B5` |
| [`pan_table.md`](pan_table.md) | DGROUP `+0054` is pan names `50L`..`50R`; not pad labels |
| [`pad_note.md`](pad_note.md) | D20: `C44E` / `CFB3` / `D9F2:000C` 64-slot paint; hit open |
| [`pgr_live_after_amx.md`](pgr_live_after_amx.md) | PGR writers after first AMX select |
| [`ivt_inventory.md`](ivt_inventory.md) | Reset-path IVT plants and writers |
| [`amx_public_api.md`](amx_public_api.md) | AMX far-call surface and TCB grammar |
| [`amx_create_table.md`](amx_create_table.md) | Create-table tasks 0–7 entries and exits |
| [`calling_convention.md`](calling_convention.md) | Far cdecl, BIOS walker, AMX registers |
| [`hex_helper.md`](hex_helper.md) | `F800:1896` prints `AL` as two hex digits via INT 43 AX=4 |
| [`irq_wrappers.md`](irq_wrappers.md) | FAC0 XA switch and AMX IRET rewrite |
| [`copy_7c92.md`](copy_7c92.md) | `8010` DGROUP grammar, consumers, writers |
| [`floppy_loader.md`](floppy_loader.md) | ROM floppy `*.SYS` boot path (MZ via INT 45), all EPROM OSes; mod rules |
| [`owner_ledger.md`](owner_ledger.md) | Seeded file-range owners; gaps are debt |
| [`padding.md`](padding.md) | Every `0xFF` window ≥ 4 bytes |
| [`patch_space.md`](patch_space.md) | Patch-write banks: the two PGR-unselected `0xFF` ranges |
| [`jev_unowned_gaps.md`](jev_unowned_gaps.md) | JEV class of the 132 unowned gaps; nothing owned |
| [`string_scan.md`](string_scan.md) | Consumer-established text; put-string `B1B1:005B` |
| [`entry_scan.md`](entry_scan.md) | Consumer-established entries; raw `9A`/`EA` are suspects |
| [`transfer_scan.md`](transfer_scan.md) | Local exits from the 143 entries; new CALLs are candidates |
| [`performance.md`](performance.md) | Cycle profiles of stock 3.50 (MAME `nec_prof`, 16 MHz): utilization map, per-event costs, headroom, ROM space, ranked optimization backlog, hardware tests; the fork ran the V53 at 2x |
| [`named_unknowns.md`](named_unknowns.md) | Ranked open uncertainties |

Do not duplicate the MPC2000XL note corpus here. Cite it when a V53
fact is shared and re-verify it against this image.
