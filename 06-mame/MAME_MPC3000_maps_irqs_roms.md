# MAME mpc3000.cpp — extracted maps / IRQs / ROMs
Source: https://github.com/mamedev/mame/blob/master/src/mame/akai/mpc3000.cpp
License: BSD-3-Clause (MAME)

## Hardware / IRQ notes (from driver header)
```
Hardware:
        CPU: NEC V53 (32 MHz)
             8086-compatible CPU
             8237-compatible DMA controller
             8254-compatible timer
             8259-compatible IRQ controller
        Floppy: uPD72069 (3000)
        SCSI: MB89352
        LCD: LC7981
        Quad-UART: TE7774 (3000)
        Panel controller CPU: NEC uPD78C10AGQ @ 12 MHz
        Sound DSP: L7A1045-L6028
            DSP's wavedata bus is 16 bits wide and has 24 address bits (32 MiB total sample space)

        DMA channel 0 is SCSI, 1 is floppy, 2 is IC31 (some sort of direct-audio stream?), and 3 is the L7A1045 DSP
        IRQ 3 is wire-OR of the 72069 FDC and 89352 SCSI
        IRQ 4 is wire-OR of all 4 TXRDYs on the TE7774
        IRQ 5 is wire-OR of RXRDY1, 2, and 3 on the TE7774
        IRQ 6 is the SMPTE sync in
        IRQ 7 is RXRDY4 on the TE7774
```

## mpc3000_map
```cpp
void mpc3000_state::mpc3000_map(address_map &map)
{
	map(0x000000, 0x07ffff).mirror(0x80000).rom().region("maincpu", 0);
	map(0x300000, 0x3fffff).ram();  // 2x HM658512 (512Kx8)
	map(0x500000, 0x500fff).ram().share("nvram");
}
```

## mpc3000_io_map
```cpp
void mpc3000_state::mpc3000_io_map(address_map &map)
{
	map(0x0000, 0x0000).w("loledlatch", FUNC(hc259_device::write_nibble_d3));
	map(0x0020, 0x0020).w("hiledlatch", FUNC(hc259_device::write_nibble_d3));
	map(0x0060, 0x006f).m(m_dsp, FUNC(l7a1045_sound_device::map));
	map(0x0080, 0x0087).rw("dioexp", FUNC(i8255_device::read), FUNC(i8255_device::write)).umask16(0x00ff);
	map(0x00a0, 0x00bf).m("spc", FUNC(mb89352_device::map)).umask16(0x00ff);
	map(0x00c0, 0x00c7).rw("sio", FUNC(te7774_device::read_cs<0>), FUNC(te7774_device::write_cs<0>)).umask16(0x00ff);
	map(0x00c8, 0x00cf).rw("sio", FUNC(te7774_device::read_cs<1>), FUNC(te7774_device::write_cs<1>)).umask16(0x00ff);
	map(0x00d0, 0x00d7).rw("sio", FUNC(te7774_device::read_cs<2>), FUNC(te7774_device::write_cs<2>)).umask16(0x00ff);
	map(0x00d8, 0x00df).rw("sio", FUNC(te7774_device::read_cs<3>), FUNC(te7774_device::write_cs<3>)).umask16(0x00ff);
	map(0x00e0, 0x00e0).rw(m_lcdc, FUNC(hd61830_device::data_r), FUNC(hd61830_device::data_w)).umask16(0x00ff);
	map(0x00e2, 0x00e2).rw(m_lcdc, FUNC(hd61830_device::status_r), FUNC(hd61830_device::control_w)).umask16(0x00ff);
	map(0x00e8, 0x00eb).m(m_fdc, FUNC(upd72069_device::map)).umask16(0x00ff);
	map(0x00e8, 0x00eb).r(FUNC(mpc3000_state::fdc_hc365_r)).umask16(0xff00);
	map(0x00f0, 0x00f7).rw("synctmr", FUNC(pit8254_device::read), FUNC(pit8254_device::write)).umask16(0x00ff);
	map(0x00f8, 0x00ff).rw("adcexp", FUNC(i8255_device::read), FUNC(i8255_device::write)).umask16(0x00ff);
}
```

## mpc3000_sub_map
```cpp
void mpc3000_state::mpc3000_sub_map(address_map &map)
{
	map(0x0000, 0x7fff).rom().region("subcpu", 0);
}
```

## dsp_map
```cpp
void mpc3000_state::dsp_map(address_map &map)
{
	map(0x0000'0000, 0x01ff'ffff).ram();
}
```

## Expected ROM filenames / hashes (do not download dumps here)
```
ROM_START( mpc3000 )
	ROM_REGION(0x80000, "maincpu", 0)   // V53 code
	ROM_SYSTEM_BIOS(0, "default", "ver 3.12")
	ROMX_LOAD( "mpc312ls.bin", 0x000000, 0x040000, CRC(d4fb6439) SHA1(555d388ed25f8b85638c325e7d9012eaa271ffa0), ROM_SKIP(1) | ROM_BIOS(0) )
	ROMX_LOAD( "mpc312ms.bin", 0x000001, 0x040000, CRC(80ee0ab9) SHA1(b8855118d59b8f73a3af5ff2e824cdaa0a9f564a), ROM_SKIP(1) | ROM_BIOS(0) )

	ROM_SYSTEM_BIOS(1, "vailixi", "ver 3.50")
	ROMX_LOAD( "3.50 vailixi lse.bin", 0x000000, 0x040000, CRC(9f3031b5) SHA1(c270a92f8ed273a1ede16388bb8f30c85ac1faab), ROM_SKIP(1) | ROM_BIOS(1) )
	ROMX_LOAD( "3.50 vailixi mso.bin", 0x000001, 0x040000, CRC(e62ebb26) SHA1(f6d080481de40bea2c94bbc96b222c5f9b7afaf4), ROM_SKIP(1) | ROM_BIOS(1) )

	ROM_SYSTEM_BIOS(2, "v311", "ver 3.11")
	ROMX_LOAD( "mpc311ls.bin", 0x000000, 0x040000, CRC(5a272061) SHA1(87cc8aef3233d95ad1febbd77b42f720d718baa3), ROM_SKIP(1) | ROM_BIOS(2) )
	ROMX_LOAD( "mpc311ms.bin", 0x000001, 0x040000, CRC(a8e177de) SHA1(b63a5c27066c03f7de56659aff183f15d95277c5), ROM_SKIP(1) | ROM_BIOS(2) )

	ROM_SYSTEM_BIOS(3, "v310", "ver 3.10")
	ROMX_LOAD( "mpc3000__ls__v3.10.am27c020__id0197.ic13_ls.bin", 0x000000, 0x040000, CRC(cbd1b3a6) SHA1(5464a57137549d9d9c47f9aafc2b89f4c0af8b31), ROM_SKIP(1) | ROM_BIOS(3) )
	ROMX_LOAD( "mpc3000__ms__v3.10.am27c020__id0197.ic14_ms.bin", 0x000001, 0x040000, CRC(e2ba1904) SHA1(27a9f047c63964fac2b453f2317b77834490983d), ROM_SKIP(1) | ROM_BIOS(3) )

	ROM_REGION(0x8000, "subcpu", 0)    // uPD78C10 panel controller code
	ROM_LOAD( "mp3000__op_v1.0.am27c256__id0110.ic602.bin", 0x000000, 0x008000, CRC(b0b783d3) SHA1(a60016184fc07ba00dcc19ba4da60e78aceff63c) )
ROM_END
```
