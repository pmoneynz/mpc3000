# Notes

Load-bearing analysis for Vailixi OS 3.50. New notes must close a named
uncertainty or correct a proven error. Status of the project:
[`../STATUS.md`](../STATUS.md).

| Note | Role |
|------|------|
| [`artifact_identity.md`](artifact_identity.md) | What the bytes are |
| [`address_model.md`](address_model.md) | How those bytes are addressed |
| [`boot_reset_to_bios_banner.md`](boot_reset_to_bios_banner.md) | First connected slice |
| [`amx_wait.md`](amx_wait.md) | AMX TCB select / idle condition |
| [`amx_first_dispatch.md`](amx_first_dispatch.md) | First `01EA` creates task 6 |
| [`int43_ax4.md`](int43_ax4.md) | Banner character → LC7981 ports |
| [`pgr_live_after_amx.md`](pgr_live_after_amx.md) | PGR writers after first AMX select |
| [`ivt_inventory.md`](ivt_inventory.md) | Reset-path IVT plants and writers |
| [`amx_public_api.md`](amx_public_api.md) | AMX far-call surface and TCB grammar |
| [`amx_create_table.md`](amx_create_table.md) | Create-table tasks 0–7 entries and exits |
| [`calling_convention.md`](calling_convention.md) | Far cdecl, BIOS walker, AMX registers |
| [`irq_wrappers.md`](irq_wrappers.md) | FAC0 XA switch and AMX IRET rewrite |
| [`copy_7c92.md`](copy_7c92.md) | `8010` DGROUP grammar, consumers, writers |
| [`owner_ledger.md`](owner_ledger.md) | Seeded file-range owners; gaps are debt |
| [`named_unknowns.md`](named_unknowns.md) | Ranked open uncertainties |

Do not duplicate the MPC2000XL note corpus here. Cite it when a V53
fact is shared and re-verify it against this image.
