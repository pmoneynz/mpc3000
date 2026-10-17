-- display_watch for the 316 profile (mods/display316.inc, put-char without INT 43
-- round trips).  The harness preamble defines LOAD_SEG and IMAGE_PHYS (physical
-- address of 3.16 image offset 0, 0x300000 + L*16).  Read-only: taps and reads.
--
-- At every put-char and string-writer entry (3.16 0427:0040, image 0x42B0, and 0427:0065, the JMPF to the cave in
-- PMONEY and the stock body otherwise; an opcode fetch with PC there) it checks
-- invariant I: [68AF] = FFh (BIOS DS 59FA) implies the LC7981 cursor address
-- (hd61830 save item m_cac) = [68AB].  It also counts INT 43 entries (0009:16A6,
-- image 0x1736) per AX, records the SS of both (the UI task's stack segment is
-- 73E1 relative, notes/port_316.md) and every distinct PS:IP that writes LC7981
-- port E0h/E2h.  Writes display_watch.txt on every change:
--   PUTC n=<entries> viol=<I violations> ...   (put-char 0427:0040)
--   PUTS n=<entries> viol=<I violations>       (string writer 0427:0065, image 0x42D5)
--   SS putc|int43 <segment rel L>=<count>
--   WRITER <PS:IP rel L> E0|E2 <count>
--   VIOL t=... cursor=... valid=... cac=... ss=... gfx=<[95C9]>  (first 20)
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local iosp = cpu.spaces["io"]
local lcdc = machine.devices[":lcdc"]
local out = os.getenv("PROBE_OUT") or "."
local cac_index
for name, index in pairs(lcdc.items) do
	if name == "m_cac" or name:match("/m_cac$") then cac_index = index end
end
assert(cac_index, "hd61830 save item m_cac not found")
local cac = emu.item(cac_index)
assert(cac.size == 2 and cac.count == 1, "m_cac is not one uint16")
local L = LOAD_SEG
local BIOS_DS = IMAGE_PHYS + 0x59FA * 16
local DG = IMAGE_PHYS + 0x609C * 16
local PUTC = IMAGE_PHYS + 0x42B0
local INT43 = IMAGE_PHYS + 0x90 + 0x16A6
local PUTC_LOG = ((L + 0x0427) * 16 + 0x40) & 0xFFFFF
local INT43_LOG = ((L + 0x0009) * 16 + 0x16A6) & 0xFFFFF
local n_int43, n_fetch_other = 0, 0
local ss_int, ax_int, writers, viol = {}, {}, {}, {}
local dirty = true

local function rel(seg) return string.format("%04X", (seg - L) & 0xFFFF) end
local first = {}
local function bump(t, k)
	t[k] = (t[k] or 0) + 1
	if t[k] == 1 then first[tostring(t) .. k] = machine.time:as_double() end
end

-- One instruction fetch can reach a tap more than once (16-bit bus, opcode and
-- prefetch reads at one emulated instant): count an entry once per instant.
local last_int43 = -1

-- Invariant I at a routine entry (an opcode fetch with PC at its first byte).
-- (the string writer's word also holds 0427:0064, a RETF, so only put-char's
-- other fetches are counted)
local function entry(name, log, count_other)
	local e = {n = 0, viol = 0, ss = {}, last = -1}
	e.check = function()
		if (cpu.state["CURPC"].value & 0xFFFFF) ~= log then
			if count_other then n_fetch_other = n_fetch_other + 1 end
			return
		end
		local t = machine.time:as_double()
		if t == e.last then return end
		e.last = t
		e.n = e.n + 1
		local ss = cpu.state["SS"].value
		bump(e.ss, rel(ss))
		local valid = prog:read_u8(BIOS_DS + 0x68AF)
		local cursor = prog:read_u16(BIOS_DS + 0x68AB)
		local c = cac:read(0)
		if valid == 0xFF and c ~= cursor then
			e.viol = e.viol + 1
			if #viol < 20 then
				viol[#viol + 1] = string.format("VIOL %s t=%.6f cursor=%04X valid=%02X cac=%04X ss=%s gfx=%02X",
					name, t, cursor, valid, c, rel(ss), prog:read_u8(DG + 0x95C9))
			end
		end
		dirty = true
	end
	return e
end
local putc = entry("putc", PUTC_LOG, true)
local puts = entry("puts", ((L + 0x0427) * 16 + 0x65) & 0xFFFFF, false)

local function at_int43()
	if (cpu.state["CURPC"].value & 0xFFFFF) ~= INT43_LOG then return end
	local t = machine.time:as_double()
	if t == last_int43 then return end
	last_int43 = t
	n_int43 = n_int43 + 1
	bump(ss_int, rel(cpu.state["SS"].value))
	bump(ax_int, string.format("%X", (cpu.state["AW"] or cpu.state["AX"]).value))
	dirty = true
end

local function lane(data, mask)
	return (mask & 0xff) ~= 0 and (data & 0xff) or ((data >> 8) & 0xff)
end

local taps = {
	prog:install_read_tap(PUTC, PUTC + 1, "dw_putc", function(offset, data, mask) putc.check() end),
	-- 0427:0065 is img 0x42D5 (odd): its word is 0x42D4..0x42D5
	prog:install_read_tap(IMAGE_PHYS + 0x42D4, IMAGE_PHYS + 0x42D5, "dw_puts", function(offset, data, mask) puts.check() end),
	prog:install_read_tap(INT43, INT43 + 1, "dw_int43", function(offset, data, mask) at_int43() end),
	iosp:install_write_tap(0xe0, 0xe3, "dw_lcd", function(offset, data, mask)
		local ps = cpu.state["PS"].value
		local key = string.format("%s:%04X %s", rel(ps), (cpu.state["CURPC"].value - (ps << 4)) & 0xffff,
			offset == 0xe2 and "E2" or "E0")
		if not writers[key] then dirty = true end
		bump(writers, key)
	end),
}
display_watch_keep = taps

emu.register_periodic(function()
	if not dirty then return end
	dirty = false
	local f = io.open(out .. "/display_watch.txt", "w")
	f:write(string.format("PUTC n=%d viol=%d int43=%d other_fetch=%d\n", putc.n, putc.viol, n_int43, n_fetch_other))
	f:write(string.format("PUTS n=%d viol=%d\n", puts.n, puts.viol))
	for k, v in pairs(putc.ss) do f:write(string.format("SS putc %s=%d first=%.6f\n", k, v, first[tostring(putc.ss) .. k])) end
	for k, v in pairs(puts.ss) do f:write(string.format("SS puts %s=%d first=%.6f\n", k, v, first[tostring(puts.ss) .. k])) end
	for k, v in pairs(ss_int) do f:write(string.format("SS int43 %s=%d first=%.6f\n", k, v, first[tostring(ss_int) .. k])) end
	for k, v in pairs(ax_int) do f:write(string.format("AX int43 %s=%d\n", k, v)) end
	for k, v in pairs(writers) do f:write(string.format("WRITER %s %d\n", k, v)) end
	for _, v in ipairs(viol) do f:write(v .. "\n") end
	f:close()
end)
