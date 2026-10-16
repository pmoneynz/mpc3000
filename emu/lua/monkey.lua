-- Read-only observer for the PMONEY / stock OS 3.16 monkey soak (monkey.py).
--
-- The wrapper script written by monkey.py defines the table MONKEY before
-- this file runs, then chains emu/probe.lua (which drives PROBE_TIMES and
-- exits MAME after the last one).  Nothing here writes MPC state: taps only
-- count and log, and RAM is only read.
--
-- MONKEY fields (all physical addresses are 24-bit, 3.16 keeps the loader's
-- third PGR: physical = 0x300000 + logical; notes/port_316.md):
--   sample        screen/queue/PC sample interval, emulated seconds
--   watch_from    emulated time from which writes are judged (after boot)
--   dg_phys       DGROUP base, key_queue its key-queue header offset
--                 (+0 capacity, +2 count; generic 8010:12BC)
--   image_phys    3.16 load image offset 0 (L*16 + 0x300000)
--   code_limit    image offset just past 3.16's last code byte (0x485EA):
--                 [0, code_limit) is 3.16 code
--   top_from      image offset of the end of 3.16's image+BSS+stack (0x7DFB0)
--   top_end       physical end of the region above it (page 61, 0x3F4000)
--   cave_phys, cave_len, cave_logical   the cave home (0 length: stock run)
--   cave_code     file with one byte per cave byte: '1' instruction, '0' data
--   records_phys  the sound directory (SND_SEG:4800, 128 x 36 bytes)
--   dump_at       list of times at which the cave, the sound directory and
--                 the write summary are dumped
--
-- Output (PROBE_OUT):
--   monkey_samples.jsonl  one line per sample: time, LCD mode/dsa/hash, text
--                         rows, LCD write count, key-queue count/capacity,
--                         distinct PCs and the top PC since the last sample,
--                         SS:SP now
--   monkey_events.log     IVT vector 0-7 dispatches, cave-code writes,
--                         foreign writes into cave data, writes above 3.16's
--                         memory outside the cave (first per 256-byte
--                         bucket), writes to 3.16 code, with PS:IP
--   monkey_cave_<t>.bin   the cave home at dump time
--   monkey_summary_<t>.json  counters and per-bucket write summaries
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, iosp = cpu.spaces["program"], cpu.spaces["io"]
local vram = machine.devices[":lcdc"].spaces["videoram"]
local out = os.getenv("PROBE_OUT") or "."
local M = MONKEY

local samples = assert(io.open(out .. "/monkey_samples.jsonl", "w"))
local events = assert(io.open(out .. "/monkey_events.log", "w"))
local nevents = 0
local MAX_EVENTS = 4000

local function now() return machine.time:as_double() end
-- Taps judge writes only from M.watch_from on; the periodic callback arms
-- them, so a tap never asks the machine for the time (hot path).
local armed = false
local st_curpc = cpu.state["CURPC"]

local function pcs()
	local ps = cpu.state["PS"].value
	return ps, (cpu.state["CURPC"].value - (ps << 4)) & 0xffff
end

local function pcstr()
	local ps, ip = pcs()
	return string.format("%04X:%04X", ps, ip)
end

local function event(fmt, ...)
	nevents = nevents + 1
	if nevents <= MAX_EVENTS then
		events:write(string.format("%.6f ", now()) .. string.format(fmt, ...) .. "\n")
		events:flush()
	end
end

-- ------------------------------------------------------------------ LCD
-- LC7981 register shadow, as probe.lua keeps it (seeded from the boot
-- snapshot's shadow when resuming).
local lcd = { ir = nil, reg = {} }
local seed = os.getenv("PROBE_LCD_SEED")
if seed and seed ~= "" then
	for k, v in string.gmatch(assert(io.open(seed)):read("a"), "(%w+)=(%d+)") do
		if k == "ir" then lcd.ir = tonumber(v) else lcd.reg[tonumber(k)] = tonumber(v) end
	end
end
local lcd_writes = 0
local function lane(data, mask)
	return (mask & 0xff) ~= 0 and (data & 0xff) or ((data >> 8) & 0xff)
end
local lcd_tap = iosp:install_write_tap(0xe0, 0xe3, "monkey_lcd", function(offset, data, mask)
	local b = lane(data, mask)
	lcd_writes = lcd_writes + 1
	if offset == 0xe2 then lcd.ir = b elseif lcd.ir ~= nil then lcd.reg[lcd.ir] = b end
end)

local function screen()
	local cols = ((lcd.reg[2] or 0x27) & 0x7f) + 1
	local vp = (((lcd.reg[1] or 0x75) >> 4) & 0x0f) + 1
	local rows = (((lcd.reg[3] or 0x3f) & 0x7f) + 1) // vp
	local dsa = ((lcd.reg[9] or 0) << 8) | (lcd.reg[8] or 0)
	local mode = lcd.reg[0] or 0
	local text = {}
	for r = 0, rows - 1 do
		local line = {}
		for c = 0, cols - 1 do
			local b = vram:read_u8((dsa + r * cols + c) & 0xffff)
			line[#line + 1] = (b >= 0x20 and b < 0x7f and b ~= 0x22 and b ~= 0x5c) and string.char(b) or "."
		end
		text[#text + 1] = '"' .. table.concat(line) .. '"'
	end
	-- FNV-1a over the 1920 bytes a 240x64 graphics screen uses (covers text mode too)
	local h = 2166136261
	for i = 0, 1919 do
		h = ((h ~ vram:read_u8((dsa + i) & 0xffff)) * 16777619) & 0xffffffff
	end
	return mode, dsa, h, table.concat(text, ",")
end

-- ------------------------------------------------------------------ RAM helpers
local function rd16(a) return prog:read_u16(a) end

-- ------------------------------------------------------------------ IVT 0-7
-- The V53 reads a vector through the live PGR: logical 0 = physical 0x300000.
local ivt_count = {}
local ivt_tap = prog:install_read_tap(0x300000, 0x30001f, "monkey_ivt", function(offset, data, mask)
	if not armed then return end
	local v = (offset - 0x300000) // 4
	-- each vector is two words; count the offset word only
	if (offset & 3) ~= 0 then return end
	ivt_count[v] = (ivt_count[v] or 0) + 1
	if ivt_count[v] <= 20 then
		local ss, sp = cpu.state["SS"].value, cpu.state["SP"].value
		event("IVT vec=%d pc=%s ss:sp=%04X:%04X", v, pcstr(), ss, sp)
	end
end)

-- ------------------------------------------------------------------ cave
local code = {}
if M.cave_len > 0 then
	local s = assert(io.open(M.cave_code, "rb")):read("a")
	for i = 1, #s do code[i - 1] = (s:byte(i) == 49) end
end
local cave_code_writes, cave_data_writes, cave_foreign_writes = 0, 0, 0
local cave_lo, cave_hi = M.cave_logical, M.cave_logical + M.cave_len
local function in_cave_pc()
	local pc = st_curpc.value
	return pc >= cave_lo and pc < cave_hi
end

-- ------------------------------------------------------------------ writes
-- 3.16 code [image 0, code_limit): every write is logged.  (Far data above
-- code_limit, e.g. the sound transfer buffer at SND_SEG:0000, is written
-- constantly and is not tapped: a tap there slowed disk-heavy runs ~10x.)
local img_writes, img_code_writes = 0, 0
local img_lo = M.image_phys
local img_tap = prog:install_write_tap(img_lo, img_lo + M.code_limit - 1, "monkey_img",
	function(offset, data, mask)
		if not armed then return end
		img_code_writes = img_code_writes + 1
		if img_code_writes <= 200 then
			event("IMGCODE image=%05X data=%04X mask=%04X pc=%s", offset - img_lo, data & 0xffff,
				mask & 0xffff, pcstr())
		end
	end)
local img_buckets = {}

-- Above 3.16's image+BSS+stack up to page 61: the cave home and free RAM.
local top_buckets = {}
local top_lo = M.image_phys + M.top_from
local cave_phys, cave_len = M.cave_phys, M.cave_len
local top_min = 0x7fffffff          -- lowest address written above 3.16's extent, outside the cave
local top_min_who = ""
local top_tap = prog:install_write_tap(top_lo, M.top_end - 1, "monkey_top", function(offset, data, mask)
	if not armed then return end
	local rel = offset - cave_phys
	if rel >= 0 and rel < cave_len then
		local is_code = (((mask & 0xff) ~= 0) and code[rel]) or (((mask & 0xff00) ~= 0) and code[rel + 1])
		if is_code then
			cave_code_writes = cave_code_writes + 1
			if cave_code_writes <= 200 then
				event("CAVECODE off=%04X data=%04X mask=%04X pc=%s", rel, data & 0xffff, mask & 0xffff, pcstr())
			end
			return
		end
		if in_cave_pc() then
			cave_data_writes = cave_data_writes + 1
			return
		end
		cave_foreign_writes = cave_foreign_writes + 1
		if cave_foreign_writes <= 200 then
			event("CAVEFOREIGN off=%04X data=%04X mask=%04X pc=%s", rel, data & 0xffff, mask & 0xffff, pcstr())
		end
		return
	end
	if offset < top_min then
		top_min = offset
		top_min_who = string.format("%.6f pc=%s ss:sp=%04X:%04X", now(), pcstr(), cpu.state["SS"].value, cpu.state["SP"].value)
	end
	local b = (offset - top_lo) >> 8
	local e = top_buckets[b]
	if not e then
		top_buckets[b] = { n = 1, t = now(), pc = pcstr(), off = offset - M.image_phys }
		event("TOPW image=%05X data=%04X mask=%04X pc=%s ss:sp=%04X:%04X", offset - M.image_phys, data & 0xffff,
			mask & 0xffff, pcstr(), cpu.state["SS"].value, cpu.state["SP"].value)
	else
		e.n = e.n + 1
	end
end)

-- ------------------------------------------------------------------ dumps
local function dump_cave(t)
	if M.cave_len == 0 then return end
	local f = assert(io.open(string.format("%s/monkey_cave_%g.bin", out, t), "wb"))
	local buf = {}
	for i = 0, M.cave_len - 1 do
		buf[#buf + 1] = string.char(prog:read_u8(M.cave_phys + i))
		if #buf == 4096 then f:write(table.concat(buf)); buf = {} end
	end
	f:write(table.concat(buf))
	f:close()
end

-- The sound directory: 128 records of 36 bytes at SND_SEG:4800 (generic A2AE:4800).
local function dump_records(t)
	if not M.records_phys then return end
	local f = assert(io.open(string.format("%s/monkey_records_%g.bin", out, t), "wb"))
	local buf = {}
	for i = 0, 128 * 36 - 1 do buf[#buf + 1] = string.char(prog:read_u8(M.records_phys + i)) end
	f:write(table.concat(buf))
	f:close()
end

local ss_min, ss_max = {}, {}
local function summary(t)
	local f = assert(io.open(string.format("%s/monkey_summary_%g.json", out, t), "w"))
	local parts = {}
	for v, n in pairs(ivt_count) do parts[#parts + 1] = string.format('"%d":%d', v, n) end
	local ivt = "{" .. table.concat(parts, ",") .. "}"
	local function buckets(tbl)
		local p = {}
		for b, e in pairs(tbl) do
			p[#p + 1] = string.format('"%d":{"n":%d,"t":%.6f,"pc":"%s","off":%d}', b, e.n, e.t, e.pc, e.off)
		end
		return "{" .. table.concat(p, ",") .. "}"
	end
	local sp, spx = {}, {}
	for ss, m in pairs(ss_min) do sp[#sp + 1] = string.format('"%04X":%d', ss, m) end
	for ss, m in pairs(ss_max) do spx[#spx + 1] = string.format('"%04X":%d', ss, m) end
	f:write(string.format('{"time":%.3f,"ivt":%s,"cave_code_writes":%d,"cave_data_writes":%d,' ..
		'"cave_foreign_writes":%d,"img_writes":%d,"img_code_writes":%d,"img_buckets":%s,"top_buckets":%s,"ss_min_sp":{%s},"ss_max_sp":{%s},"top_min_image":%d,"top_min_who":"%s","events":%d}\n',
		t, ivt, cave_code_writes, cave_data_writes, cave_foreign_writes, img_writes, img_code_writes, buckets(img_buckets),
		buckets(top_buckets), table.concat(sp, ","), table.concat(spx, ","),
		top_min < 0x7fffffff and (top_min - M.image_phys) or -1, top_min_who, nevents))
	f:close()
end

-- ------------------------------------------------------------------ periodic
local next_sample = M.sample_from
local pc_hist, pc_n = {}, 0
local dump_idx = 1
emu.register_periodic(function()
	local t = now()
	if not armed and t >= M.watch_from then armed = true end
	local ps, ip = pcs()
	local key = (ps << 16) | ip
	pc_hist[key] = (pc_hist[key] or 0) + 1
	pc_n = pc_n + 1
	local ss, sp = cpu.state["SS"].value, cpu.state["SP"].value
	if t >= M.watch_from then
		if ss_min[ss] == nil or sp < ss_min[ss] then ss_min[ss] = sp end
		if ss_max[ss] == nil or sp > ss_max[ss] then ss_max[ss] = sp end
	end
	if t >= next_sample then
		local mode, dsa, h, text = screen()
		local cap, cnt = rd16(M.dg_phys + M.key_queue), rd16(M.dg_phys + M.key_queue + 2)
		local distinct, top, topn = 0, 0, 0
		for k, n in pairs(pc_hist) do
			distinct = distinct + 1
			if n > topn then top, topn = k, n end
		end
		samples:write(string.format('{"t":%.3f,"mode":%d,"dsa":%d,"hash":%d,"lcdw":%d,"kq":[%d,%d],' ..
			'"pcs":%d,"top":"%04X:%04X","topn":%d,"n":%d,"sssp":"%04X:%04X","rows":[%s]}\n',
			t, mode, dsa, h, lcd_writes, cnt, cap, distinct, top >> 16, top & 0xffff, topn, pc_n, ss, sp, text))
		samples:flush()
		lcd_writes = 0
		pc_hist, pc_n = {}, 0
		next_sample = next_sample + M.sample
	end
	if dump_idx <= #M.dump_at and t >= M.dump_at[dump_idx] then
		dump_cave(M.dump_at[dump_idx])
		dump_records(M.dump_at[dump_idx])
		summary(M.dump_at[dump_idx])
		dump_idx = dump_idx + 1
	end
end)

-- ------------------------------------------------------------------ lean probe
-- M.lean: this script also does probe.lua's job for emu/mpc3k.run (screens.txt
-- at each PROBE_TIMES entry, then exit) without probe.lua's taps on the whole
-- I/O space, which call Lua on every external I/O access.
if M.lean then
	local times = {}
	for x in string.gmatch(os.getenv("PROBE_TIMES") or "", "[^,]+") do times[#times + 1] = tonumber(x) end
	local screens = assert(io.open(out .. "/screens.txt", "w"))
	local pidx = 1
	emu.register_periodic(function()
		if pidx > #times or now() < times[pidx] then return end
		local cols = ((lcd.reg[2] or 0x27) & 0x7f) + 1
		local vp = (((lcd.reg[1] or 0x75) >> 4) & 0x0f) + 1
		local rows = (((lcd.reg[3] or 0x3f) & 0x7f) + 1) // vp
		local dsa = ((lcd.reg[9] or 0) << 8) | (lcd.reg[8] or 0)
		screens:write(string.format("@ %.3f mode=%02X dsa=%04X %dx%d\n", times[pidx], lcd.reg[0] or 0, dsa, cols, rows))
		for r = 0, rows - 1 do
			local line = {}
			for c = 0, cols - 1 do
				local b = vram:read_u8((dsa + r * cols + c) & 0xffff)
				line[#line + 1] = (b >= 0x20 and b < 0x7f) and string.char(b) or "."
			end
			screens:write("|" .. table.concat(line) .. "|\n")
		end
		screens:flush()
		pidx = pidx + 1
		if pidx > #times then machine:exit() end
	end)
end

monkey_keep_alive = { lcd_tap, ivt_tap, img_tap, top_tap }
