# 07-rom — binary inventory vs MAME

## ★ SPECIAL: v3.16 maintenance upgrade (floppy, not EPROM)

Path: [`v3.16 maintenance upgrade/`](v3.16%20maintenance%20upgrade/)

| Item | Detail |
|------|--------|
| Kind | **Floppy-bootable RAM OS**, not an EPROM burn |
| Payload | `M3K316.SYS` (458047 B, SHA1 `b45b017721f0e59974e50de93040ccd1f973ad23`) |
| Notes | `M3K316.pdf` — install + changelog |
| Permanence | Lost on power-off; needs ROM ≥ 3.11 to boot |
| Doc | [`v3.16 maintenance upgrade/README.md`](v3.16%20maintenance%20upgrade/README.md) |

Do not confuse with the interleaved 256 KiB LS/MS EPROM pairs below.

---

Checked 2026-09-21. SHA1s from files on disk. MAME refs: `06-mame/MAME_MPC3000_maps_irqs_roms.md`.

MAME main CPU: interleaved **256 KiB** LS + MS (`ROM_SKIP(1)`). Panel MCU: **32 KiB**.

| File | Size | SHA1 | SHA-256 | Status |
|------|------|------|---------|--------|
| `Vailixi 3.50/3.50 Vailixi (LSE).BIN` | 262144 | `c270a92f8ed273a1ede16388bb8f30c85ac1faab` | `cb4531fab4f2a43d3ad71465ac9efbe4bd6c3b23401cdbac379eea37234c4004` | MATCH vailixi LS |
| `Vailixi 3.50/3.50 Vailixi (MSO).BIN` | 262144 | `f6d080481de40bea2c94bbc96b222c5f9b7afaf4` | `514c745dea6bb711d19cf6e09bb4e7987f732c1bfa6b01857068c9982e295801` | MATCH vailixi MS |
| `Vailixi 3.50/vailixi-docs.pdf` | 404143 | `—` | docs |
| `v3.08/MPC3000_V3.08_LSB.BIN` | 262144 | `d8b2a9d3cc65223f40c2c6954a842160cb58fd9e` | full size, not in MAME set |
| `v3.08/MPC3000_V3.08_MSB.BIN` | 262144 | `59f1cdc8dec1dc49f6b337da1f9bbc1bfaf259d8` | full size, not in MAME set |
| `v3.11/MPC311LS.BIN` | 262144 | `87cc8aef3233d95ad1febbd77b42f720d718baa3` | MATCH mpc311ls |
| `v3.11/MPC311MS.BIN` | 262144 | `b63a5c27066c03f7de56659aff183f15d95277c5` | MATCH mpc311ms |
| `v3.12/MPC312LS.BIN` | 262144 | `555d388ed25f8b85638c325e7d9012eaa271ffa0` | MATCH mpc312ls |
| `v3.12/MPC312MS.BIN` | 262144 | `b8855118d59b8f73a3af5ff2e824cdaa0a9f564a` | MATCH mpc312ms |

## Summary

- **★ Floppy maintenance OS 3.16** in `v3.16 maintenance upgrade/` — RAM boot via FDC, **not** EPROM. See that folder’s README.


- **Vailixi 3.50 linear (LS even, MS odd):** 524288 bytes, SHA-256 `a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`. Builder: `tools/linear_rom.py`.
- **MAME-matched OS dumps:** Vailixi 3.50, stock 3.11, stock 3.12 (all LS+MS).
- **Also present:** v3.08 full 256 KiB pair (not in current MAME bios list).
- **Still missing:** panel µPD78C10 / AM27C256 ROM (`subcpu`, SHA1 `a60016184fc07ba00dcc19ba4da60e78aceff63c`).
