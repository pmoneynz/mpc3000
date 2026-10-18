-- Lazy Chop observer for the 316 profile (mods/lazychop316.inc).  The harness
-- preamble (emu/harness.py observer()) defines CAVE (map offsets), LOAD_SEG,
-- CAVE_SEG, CAVE_PHYS, DG_SEG, DG_PHYS, SND_SEG and IMAGE_PHYS.  Read-only,
-- except LC_INJECT_BASE and LC_INJECT_DG (below), test injections of the TCT0
-- time base and of DGROUP bytes.
-- lazychop.log lines (t = emulated seconds, cs/ip runtime):
--   ISR    t raw    the owned press path, right after its timestamp call (lc_isr_stamped)
--   T0     t raw    the take's t0, right after its timestamp call (lc_t0_stamped)
--   NOTEON t        the stock note event entry 20DA:000E executes
--   RING5  t count  ring 5 (RING_SEG:06AC) count word written, with the writer's cs:ip
--   KEYON  t ch start step   DSP key-on (OUT 68h bit 8): the channel's wave address and pitch step registers
--   KEY    t key    a key the view read (lc_dispatch, BL)
--   AUD    t        an audition of the view returns from CFC6:0CE9 (aud_range.return_from_stock)
--   STOP   t ch caller  the one-channel stop 234D:0000 (OUT 60h at 234D:0014)
--   TS     t ss ui  2B50:0194 entered; ui=1 on the UI task's stack
--   SNAP   {json}   cave and stock state at each PROBE_TIMES time
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local iosp = cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/lazychop.log", "w"))
local from = tonumber(os.getenv("LC_FROM") or "0")

local function now() return machine.time:as_double() end
local function csip()
	local cs = tonumber(cpu.state["PS"].value)
	return cs, (cpu.state["CURPC"].value - (cs << 4)) & 0xffff
end
local function phys(seg, off)
	local a = ((seg << 4) + off) & 0xfffff
	if cpu.state["XA"].value ~= 0 then
		local pgr = iosp:read_u16(0xff00 + ((a >> 14) & 0x3f) * 2)
		return ((pgr & 0x3ff) << 14) | (a & 0x3fff)
	end
	return a
end
local function rd8(seg, off) return prog:read_u8(phys(seg, off & 0xffff)) end
local function rd16(seg, off) return rd8(seg, off) | (rd8(seg, off + 1) << 8) end
local function rd32(seg, off) return rd16(seg, off) | (rd16(seg, off + 2) << 16) end
local function cv8(name, k) return CAVE[name] and rd8(CAVE_SEG, CAVE[name] + (k or 0)) or 0 end
local function cv32(name, k) return rd32(CAVE_SEG, CAVE[name] + (k or 0)) end
local function dg8(off) return rd8(DG_SEG, off) end

local taps = {}
-- Execution of a cave label: a read of its first byte while CURPC is there.
local function exec_tap(name, fn)
	local logical = ((CAVE_SEG << 4) + CAVE[name]) & 0xfffff
	local p = CAVE_PHYS + CAVE[name]
	taps[#taps + 1] = prog:install_read_tap(p & ~1, p | 1, "lc_x_" .. name, function(offset, data, mask)
		if (cpu.state["CURPC"].value & 0xfffff) ~= logical then return end
		fn()
	end)
end
local function dxax()
	return ((tonumber(cpu.state["DW"].value) & 0xffff) << 16) | (tonumber(cpu.state["AW"].value) & 0xffff)
end
local last_isr, last_t0 = -1, -1
exec_tap("lc_isr_stamped", function()
	local t = now()
	if t - last_isr < 0.00001 then return end
	last_isr = t
	log:write(string.format("ISR t=%.7f raw=%u slot=%u\n", t, dxax(), dg8(0xD399)))
end)
exec_tap("lc_t0_stamped", function()
	local t = now()
	if t - last_t0 < 0.00001 then return end
	last_t0 = t
	log:write(string.format("T0 t=%.7f raw=%u\n", t, dxax()))
end)

-- Every view audition passes the one CFC6:0CE9 call site (R2).
local last_aud = -1
exec_tap("aud_range.return_from_stock", function()
	local t = now()
	if t - last_aud < 0.00001 then return end
	last_aud = t
	log:write(string.format("AUD t=%.7f\n", t))
end)

-- Every key the view reads (lc_dispatch, BL).
exec_tap("lc_dispatch", function()
	local t = now()
	if t < from then return end
	log:write(string.format("KEY t=%.7f key=%u phase=%u\n", t, tonumber(cpu.state["BW"].value) & 0xff, cv8("lc_phase")))
end)

-- Stock code entries (3.16 image offsets).
local function stock_tap(kind, img)
	local seg, off = img >> 4, img & 15
	local logical = (((LOAD_SEG + seg) & 0xffff) << 4) + off
	local p = IMAGE_PHYS + img
	local last = -1
	taps[#taps + 1] = prog:install_read_tap(p & ~1, p | 1, "lc_s_" .. kind, function(offset, data, mask)
		if (cpu.state["CURPC"].value & 0xfffff) ~= (logical & 0xfffff) then return end
		local t = now()
		if t < from or t - last < 0.00001 then return end
		last = t
		log:write(string.format("%s t=%.7f\n", kind, t))
	end)
end
stock_tap("NOTEON", 0x20DAE)            -- 20DA:000E note event entry

-- 2B50:0194, the TCT0 timestamp, with the caller's stack segment (the UI task's
-- is L+73E1; the interrupt stack is another).
do
	local img = 0x2B694
	local logical = ((((LOAD_SEG + 0x2B50) & 0xffff) << 4) + 0x194) & 0xfffff
	local p = IMAGE_PHYS + img
	local last = -1
	taps[#taps + 1] = prog:install_read_tap(p & ~1, p | 1, "lc_s_ts", function(offset, data, mask)
		if (cpu.state["CURPC"].value & 0xfffff) ~= logical then return end
		local t = now()
		if t < from or t - last < 0.000005 then return end
		last = t
		log:write(string.format("TS t=%.7f ss=%04X ui=%d\n", t, tonumber(cpu.state["SS"].value),
			tonumber(cpu.state["SS"].value) == ((LOAD_SEG + 0x73E1) & 0xffff) and 1 or 0))
	end)
end

local RING = 0x300000 + ((LOAD_SEG + 0x77CA) & 0xffff) * 16 + 0x06AE
taps[#taps + 1] = prog:install_write_tap(RING, RING + 1, "lc_ring5", function(offset, data, mask)
	if now() < from then return end
	local cs, ip = csip()
	log:write(string.format("RING5 t=%.7f count=%u cs=%04X ip=%04X\n", now(), data & 0xffff, cs, ip))
end)

-- DSP: key-on with the channel's start register (as wave_playback316.lua), stops.
local STOP_CS, STOP_IP = (LOAD_SEG + 0x234D) & 0xffff, 0x0014
local sel_ch, sel_reg = 0, 0
local regs = {}
local function lanes(reg, ch)
	regs[reg] = regs[reg] or {}
	regs[reg][ch] = regs[reg][ch] or {0, 0, 0}
	return regs[reg][ch]
end
taps[#taps + 1] = iosp:install_write_tap(0x60, 0x6f, "lc_dsp", function(offset, data, mask)
	local cs, ip = csip()
	if offset == 0x60 then
		if mask & 0x00ff ~= 0 then sel_ch = data & 0x1f end
		if mask & 0xff00 ~= 0 then sel_reg = (data >> 8) & 0x0f end
		if cs == STOP_CS and ip == STOP_IP and mask == 0xffff and (data >> 8) & 0xff == 0x04 and now() >= from then
			local ss = tonumber(cpu.state["SS"].value)
			local bp = tonumber(cpu.state["SP"].value)
			log:write(string.format("STOP t=%.7f ch=%u caller=%04X\n", now(), data & 0x1f, rd16(ss, (bp + 4) & 0xffff)))
		end
	elseif offset >= 0x62 and offset <= 0x66 then
		local lane = (offset - 0x62) // 2 + 1
		local v = lanes(sel_reg, sel_ch)
		v[lane] = ((v[lane] & (~mask & 0xffff)) | (data & mask)) & 0xffff
	elseif offset == 0x68 and data & mask & 0x0100 ~= 0 and now() >= from then
		local s = lanes(0, sel_ch)
		local s48 = s[1] | (s[2] << 16) | (s[3] << 32)
		log:write(string.format("KEYON t=%.7f ch=%u start=%u step=%u cs=%04X ip=%04X\n", now(), sel_ch,
			(s48 >> 12) & 0xffffff, lanes(1, sel_ch)[1], cs, ip))
	end
end)

-- State snapshots.
local times = {}
for v in string.gmatch(os.getenv("LC_SNAPSHOTS") or os.getenv("PROBE_TIMES") or "", "[^,]+") do
	times[#times + 1] = tonumber(v)
end
local REC_SEG = (LOAD_SEG + 0x485F) & 0xffff     -- program records (302F:0029)
local function list(n, fn)
	local t = {}
	for i = 0, n - 1 do t[#t + 1] = tostring(fn(i)) end
	return "[" .. table.concat(t, ",") .. "]"
end
local function str(seg, off, n)
	local s = {}
	for i = 0, n - 1 do
		local c = rd8(seg, off + i)
		if c == 0 then break end
		s[#s + 1] = (c >= 32 and c < 127 and c ~= 34 and c ~= 92) and string.char(c) or "?"
	end
	return '"' .. table.concat(s) .. '"'
end
local function program(i)
	local size, count = rd16(REC_SEG, 0), rd16(REC_SEG, 2)
	if i >= count then return "null" end
	local base = size * i + 4
	return string.format('{"name":%s,"sounds":%s,"poly":%s,"map":%s}', str(REC_SEG, base, 16),
		list(64, function(k) return rd8(REC_SEG, base + 0x3E + k * 0x18) end),
		list(64, function(k) return rd8(REC_SEG, base + 0x3E + k * 0x18 + 6) end),
		list(64, function(k) return rd8(REC_SEG, base + 0x73E + k) end))
end
local function mute(i)
	local b = CAVE.mute_states + i * 33
	return string.format('{"enabled":%u,"groups":%s}', rd8(CAVE_SEG, b),
		list(64, function(k) return (rd8(CAVE_SEG, b + 1 + (k >> 1)) >> (4 * (k & 1))) & 15 end))
end
local function snap(t)
	local n = cv8("zones_count")
	local nch = cv8("lc_nchops")
	local cur = dg8(0xE2FB)
	local progs = {}
	for i = 0, 23 do progs[#progs + 1] = program(i) end
	local mutes = {}
	for i = 0, 23 do mutes[#mutes + 1] = mute(i) end
	log:write(string.format('SNAP {"t":%.3f,"owned":%u,"phase":%u,"head":%u,"tail":%u,"dropped":%u,'
		.. '"nchops":%u,"chops":%s,"mode":%u,"valid":%u,"count":%u,"current":%u,"sel":%u,"onview":%u,'
		.. '"pairs":%s,"captured":%u,"aud":%s,"offset":%d,"snap":%u,"note":%u,"fine":%u,"held":%u,"bank":%u,'
		.. '"program":%u,"owner":%s,"tags":%s,"keys":%u,"pressure":%s,"cvstatus":%u,"box":%u,"mode_key":%u,'
		.. '"diskok":%u,"diskrc":%u,"programs":[%s],"mute":[%s]}\n',
		t, cv8("lc_owned"), cv8("lc_phase"), cv8("lc_head"), cv8("lc_tail"), cv8("lc_dropped"),
		nch, list(nch, function(k) return cv32("lc_chops", 4 * k) end),
		cv8("zones_mode"), cv8("zones_valid"), n, cv8("zones_current"), cv8("sel"), cv8("onview"),
		list(n, function(k) return "[" .. cv32("zones_pairs", 8 * k) .. "," .. cv32("zones_pairs", 8 * k + 4) .. "]" end),
		rd16(CAVE_SEG, CAVE.lc_captured), list(cv8("lc_aud_n"), function(k) return cv8("lc_aud_ch", k) end),
		(cv8("lc_offset") + 128) % 256 - 128, cv8("lc_snap"), cv8("lc_note"), cv8("fine"), dg8(0x9447), dg8(0xD38F),
		cur, list(32, function(k) return dg8(0xE286 + k) end),
		list(32, function(k) return cv8("mute_voice_program", k) end), rd16(DG_SEG, 0x12A6),
		list(64, function(k) return dg8(0x9548 + 35 + k) end), CAVE.lc_cv_status and rd16(CAVE_SEG, CAVE.lc_cv_status) or 0,
		cv8("lc_box"), dg8(0xD4B8), cv8("lc_disk_ok"), CAVE.lc_disk_rc and rd16(CAVE_SEG, CAVE.lc_disk_rc) or 0,
		table.concat(progs, ","), table.concat(mutes, ",")))
	log:flush()
	local records = assert(io.open(string.format("%s/records_%g.bin", out, t), "wb"))
	for i = 0, 128 * 0x24 - 1 do records:write(string.char(rd8(SND_SEG, 0x4800 + i))) end
	records:close()
end
local si = 1
-- LC_INJECT_BASE="t:value": at emulated time t, write value to the TCT0 time
-- base DGROUP:D501 (the 32-bit base the 100 Hz ISR 2B50:0018 advances), so a
-- take can cross its 2^32 wrap (spec A7).  The only state any observer writes.
-- LC_INJECT_DG="t:off:value,...": at emulated time t write the DGROUP byte off
-- (hex) (emu/test_lazychop.py "errbox": the flags of BDE3:000E's error box).
local dg_inject = {}
for t, o, v in string.gmatch(os.getenv("LC_INJECT_DG") or "", "([^:,]+):(%x+):(%x+)") do
	dg_inject[#dg_inject + 1] = {tonumber(t), tonumber(o, 16), tonumber(v, 16)}
end
emu.register_periodic(function()
	local t = now()
	for _, d in ipairs(dg_inject) do
		if not d.done and t >= d[1] then
			prog:write_u8(phys(DG_SEG, d[2]), d[3])
			log:write(string.format("INJECTDG t=%.7f off=%04X v=%02X\n", t, d[2], d[3]))
			d.done = true
		end
	end
end)
local inject_t, inject_v = string.match(os.getenv("LC_INJECT_BASE") or "", "^([^:]+):(.+)$")
inject_t, inject_v = tonumber(inject_t), tonumber(inject_v)
emu.register_periodic(function()
	local t = now()
	if inject_t and t >= inject_t then
		for k = 0, 3 do
			prog:write_u8(phys(DG_SEG, 0xD501 + k), (inject_v >> (8 * k)) & 0xff)
		end
		log:write(string.format("INJECT t=%.7f base=%u\n", t, inject_v))
		inject_t = nil
	end
	if si <= #times and t >= times[si] then
		snap(times[si])
		si = si + 1
	end
	log:flush()
end)
-- LC_DEBUG="a:b": also the time-base writes and the ICU port writes in [a, b].
local dbg_a, dbg_b = string.match(os.getenv("LC_DEBUG") or "", "^([^:]+):(.+)$")
if dbg_a then
	dbg_a, dbg_b = tonumber(dbg_a), tonumber(dbg_b)
	local base = DG_PHYS + 0xD501
	taps[#taps + 1] = prog:install_write_tap(base & ~1, (base + 3) | 1, "lc_dbg_base", function(offset, data, mask)
		local t = now()
		if t < dbg_a or t > dbg_b then return end
		local cs, ip = csip()
		log:write(string.format("BASE t=%.7f off=%06X data=%04X mask=%04X cs=%04X ip=%04X\n", t, offset, data, mask, cs, ip))
	end)
	taps[#taps + 1] = iosp:install_write_tap(0xc010, 0xc011, "lc_dbg_icu", function(offset, data, mask)
		local t = now()
		if t < dbg_a or t > dbg_b then return end
		local cs, ip = csip()
		log:write(string.format("ICU t=%.7f port=%04X data=%04X mask=%04X cs=%04X ip=%04X\n", t, offset, data, mask, cs, ip))
	end)
end
lazychop_keep = taps
