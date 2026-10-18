-- Input Thru observer for the 316 profile (mods/thru316.inc).  The harness
-- preamble (emu/harness.py observer()) defines CAVE (map offsets), LOAD_SEG,
-- CAVE_SEG, CAVE_PHYS, DG_SEG and IMAGE_PHYS.  Installs taps and reads memory
-- only; never writes MPC state.
-- thru.log lines (t = emulated seconds, cs/ip runtime, from THRU_FROM on):
--   DSP   t port data cs ip   OUT to 60h..6Fh from the cave, and every OUT 68h
--   KEYON t ch cs ip          OUT 68h with bit 8 (key on the selected channel)
--   DMA   t port data cs ip   OUT to C000h..C00Fh
--   PPI   t port data cs ip   OUT to 80h..86h and F8h..FEh (the 8255s)
--   X     t name              a cave entry point executes
--   SNAP  {json}              Thru and allocator state at each PROBE_TIMES time
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local iosp = cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/thru.log", "w"))
local from = tonumber(os.getenv("THRU_FROM") or "0")

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
local function cv8(name, k) return rd8(CAVE_SEG, CAVE[name] + (k or 0)) end
local function dg8(off) return rd8(DG_SEG, off) end

local taps = {}
-- A byte OUT to an odd port reaches the 16-bit tap at port-1 with mask FF00h.
local function line(kind, port, data, mask)
	if mask == 0xff00 then port = port + 1 end
	local cs, ip = csip()
	log:write(string.format("%s t=%.7f port=%04X data=%04X cs=%04X ip=%04X\n", kind, now(), port, data, cs, ip))
end

local sel_ch = 0
taps[#taps + 1] = iosp:install_write_tap(0x60, 0x6f, "thru_dsp", function(offset, data, mask)
	if offset == 0x60 and mask & 0x00ff ~= 0 then sel_ch = data & 0x1f end
	if now() < from then return end
	local cs = csip()
	local value = (mask == 0xff00) and (data >> 8) or (data & mask)
	if cs == CAVE_SEG or offset == 0x68 then line("DSP", offset, value, mask) end
	if offset == 0x68 and data & mask & 0x0100 ~= 0 then
		local c, ip = csip()
		log:write(string.format("KEYON t=%.7f ch=%u cs=%04X ip=%04X\n", now(), sel_ch, c, ip))
	end
end)
-- The V53 DMAU (OPHA C0h, DULA 00h: ports C000h..C00Fh) sits in the CPU's
-- internal I/O space at the port's low byte.  Loading the boot snapshot
-- re-maps that space (v5x interface_post_load), which drops earlier taps, so
-- this one is installed from the periodic callback once emulation runs.
local dma_tap = nil
local function install_dma_tap()
	local internal = cpu.spaces["internal_io"]
	if dma_tap or not internal then return end
	dma_tap = internal:install_write_tap(0x00, 0x0f, "thru_dma", function(offset, data, mask)
		if now() < from then return end
		line("DMA", 0xc000 | offset, (mask == 0xff00) and (data >> 8) or (data & mask), mask)
	end)
	taps[#taps + 1] = dma_tap
end
local function ppi(lo, hi)
	taps[#taps + 1] = iosp:install_write_tap(lo, hi, "thru_ppi" .. lo, function(offset, data, mask)
		if now() < from then return end
		line("PPI", offset, (mask == 0xff00) and (data >> 8) or (data & mask), mask)
	end)
end
ppi(0x80, 0x87)
ppi(0xf8, 0xff)

-- Execution of a cave label: a read of its first byte while CURPC is there.
local function exec_tap(name)
	local logical = ((CAVE_SEG << 4) + CAVE[name]) & 0xfffff
	local p = CAVE_PHYS + CAVE[name]
	local last = -1
	taps[#taps + 1] = prog:install_read_tap(p & ~1, p | 1, "thru_x_" .. name, function(offset, data, mask)
		if (cpu.state["CURPC"].value & 0xfffff) ~= logical then return end
		local t = now()
		if t < from or t - last < 0.000002 then return end
		last = t
		log:write(string.format("X t=%.7f name=%s\n", t, name))
	end)
end
for _, name in ipairs({"thru_sync", "thru_input_start", "thru_input_stop", "thru_stage_start",
		"thru_stage_stop", "thru_xfer_guard.wrap", "thru_fdc_enter", "thru_fdc_leave", "thru_reg1_guard", "thru_sample_wrap",
		"thru_page", "thru_stop_guard.skip", "thru_alloc_free.skip"}) do
	exec_tap(name)
end

local function list(n, fn)
	local t = {}
	for i = 0, n - 1 do t[#t + 1] = tostring(fn(i)) end
	return "[" .. table.concat(t, ",") .. "]"
end
local function snap(t)
	-- Allocation table entry 0 (DGROUP D535): type, index, start dword, length dword.
	log:write(string.format('SNAP {"t":%.3f,"in_on":%u,"stage_on":%u,"hold":%u,"status":%u,"mode":%u,'
		.. '"input":%u,"resv":%s,"set_mode":%u,"set_input":%u,"set_level":%u,"mix":%u,"banks":%u,'
		.. '"pool_start":%u,"pool_len":%u,"owner":%s,"timer":%s,"dma_lo":%u,"dma_hi":%u,"wave":%s}\n',
		t, cv8("thru_in_on"), cv8("thru_stage_on"), cv8("thru_hold"), cv8("thru_status"),
		cv8("thru_cur_mode"), cv8("thru_cur_input"), list(32, function(k) return cv8("thru_resv", k) end),
		dg8(0x831F), dg8(0x8320), dg8(0x8321), cv8("thru_mix"), rd16(DG_SEG, 0xF16A),
		rd32(DG_SEG, 0xD535 + 2), rd32(DG_SEG, 0xD535 + 6),
		list(32, function(k) return dg8(0xE286 + k) end),
		list(32, function(k) return rd16(DG_SEG, 0xE13D + 2 * k) end),
		rd16(CAVE_SEG, CAVE.thru_dma_lo), cv8("thru_dma_hi"),
		list(10, function(k) return rd16(CAVE_SEG, CAVE.thru_wave + 2 * k) end)))
	log:flush()
end
local times = {}
for v in string.gmatch(os.getenv("THRU_SNAPSHOTS") or os.getenv("PROBE_TIMES") or "", "[^,]+") do
	times[#times + 1] = tonumber(v)
end
local si = 1
emu.register_periodic(function()
	install_dma_tap()
	if si > #times or now() < times[si] then return end
	snap(times[si])
	si = si + 1
end)
THRU_TAPS = taps
