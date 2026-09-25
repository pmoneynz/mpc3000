-- Headless probe for the MAME mpc3000 driver, driven by emu/mpc3k.py.
-- Env: PROBE_OUT (dir), PROBE_TIMES (comma list of emulated seconds).
local out = os.getenv("PROBE_OUT") or "."
local times = {}
for t in string.gmatch(os.getenv("PROBE_TIMES") or "5,15,30", "[^,]+") do
	times[#times + 1] = tonumber(t)
end

local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local iosp = cpu.spaces["io"]
local vram = machine.devices[":lcdc"].spaces["videoram"]

local lcdlog = io.open(out .. "/lcd_io.log", "w")
local portlog = io.open(out .. "/io_first.log", "w")
local screens = io.open(out .. "/screens.txt", "w")
local hexdump = io.open(out .. "/screens_hex.txt", "w")
local pixfile = io.open(out .. "/lcd_pixels.txt", "w")

-- LC7981 registers as last written (instruction register selects).
local lcd = { ir = nil, reg = {} }
local seen = {}

local function now()
	return machine.time:as_double()
end

local function pc()
	local ps = cpu.state["PS"].value
	return string.format("%04X:%04X", ps, (cpu.state["CURPC"].value - (ps << 4)) & 0xffff)
end

local function lane(data, mask)
	return (mask & 0xff) ~= 0 and (data & 0xff) or ((data >> 8) & 0xff)
end

local lcd_tap = iosp:install_write_tap(0xe0, 0xe3, "probe_lcd", function(offset, data, mask)
	local b = lane(data, mask)
	if offset == 0xe2 then
		lcd.ir = b
	elseif lcd.ir ~= nil then
		lcd.reg[lcd.ir] = b
		-- 0x0C is "write display data"; logging every character is noise.
		if lcd.ir ~= 0x0c then
			lcdlog:write(string.format("%.6f %s IR=%02X D=%02X\n", now(), pc(), lcd.ir, b))
		end
	end
end)

local function first(kind)
	return function(offset, data, mask)
		local key = kind .. offset
		if not seen[key] then
			seen[key] = true
			portlog:write(string.format("%.6f %s %s %04X data=%04X mask=%04X\n",
				now(), pc(), kind, offset, data, mask))
		end
	end
end
local rtap = iosp:install_read_tap(0x0000, 0xffff, "probe_r", first("R"))
local wtap = iosp:install_write_tap(0x0000, 0xffff, "probe_w", first("W"))

-- Env PROBE_TRACE: comma list of hex I/O ports whose every access is logged.
local traced = {}
local tracelog = io.open(out .. "/io_trace.log", "w")
for p in string.gmatch(os.getenv("PROBE_TRACE") or "", "[^,]+") do
	local port = tonumber(p, 16)
	local word = port & ~1
	local shift = (port & 1) * 8
	local function logger(kind)
		return function(offset, data, mask)
			if (mask >> shift) & 0xff ~= 0 then
				tracelog:write(string.format("%.6f %s %s %04X %02X\n", now(), pc(), kind, port, (data >> shift) & 0xff))
			end
		end
	end
	traced[#traced + 1] = iosp:install_read_tap(word, word | 1, "probe_tr" .. p, logger("R"))
	traced[#traced + 1] = iosp:install_write_tap(word, word | 1, "probe_tw" .. p, logger("W"))
end

-- Character mode: registers 1/2 give pitch and chars per line, 3 the
-- time-division count, 8/9 the display start address.
local function dump_text(t)
	local cols = ((lcd.reg[2] or 0x27) & 0x7f) + 1
	local vp = (((lcd.reg[1] or 0x75) >> 4) & 0x0f) + 1
	local rows = (((lcd.reg[3] or 0x3f) & 0x7f) + 1) // vp
	local dsa = ((lcd.reg[9] or 0) << 8) | (lcd.reg[8] or 0)
	local mode = lcd.reg[0] or 0
	screens:write(string.format("@ %.3f mode=%02X dsa=%04X %dx%d\n", t, mode, dsa, cols, rows))
	hexdump:write(string.format("@ %.3f\n", t))
	for r = 0, rows - 1 do
		local line = {}
		local hex = {}
		for c = 0, cols - 1 do
			local b = vram:read_u8((dsa + r * cols + c) & 0xffff)
			line[#line + 1] = (b >= 0x20 and b < 0x7f) and string.char(b) or "."
			hex[#hex + 1] = string.format("%02X", b)
		end
		screens:write("|" .. table.concat(line) .. "|\n")
		hexdump:write(table.concat(hex, " ") .. "\n")
	end
	screens:flush()
	hexdump:flush()

	-- Native LCD pixels as '#' (lit) / '.' rows, for glass-photo comparison.
	local scr = machine.screens:at(1)
	local pix, w, h = scr:pixels()
	local lit = {}
	local minv, maxv = math.huge, -math.huge
	for i = 0, w * h - 1 do
		local v = (string.unpack("<I4", pix, i * 4 + 1) >> 16) & 0xff
		lit[i] = v
		minv, maxv = math.min(minv, v), math.max(maxv, v)
	end
	pixfile:write(string.format("@ %.3f %dx%d\n", t, w, h))
	for y = 0, h - 1 do
		local row = {}
		for x = 0, w - 1 do
			row[#row + 1] = (lit[y * w + x] * 2 > minv + maxv) and "#" or "."
		end
		pixfile:write(table.concat(row) .. "\n")
	end
	pixfile:flush()
end

-- Env PROBE_PRESS: ';'-separated "time:port:field:hold" input presses
-- through MAME's own input fields (exercises the driver's panel HLE).
local presses = {}
for item in string.gmatch(os.getenv("PROBE_PRESS") or "", "[^;]+") do
	local t, port, field, hold = string.match(item, "^([^:]+):([^:]+):([^:]+):([^:]+)$")
	local f = machine.ioport.ports[":" .. port].fields[field]
	presses[#presses + 1] = { on = tonumber(t), off = tonumber(t) + tonumber(hold), field = f, state = 0 }
end

local function drive_inputs()
	local t = now()
	for _, p in ipairs(presses) do
		local want = (t >= p.on and t < p.off) and 1 or 0
		if want ~= p.state then
			p.field:set_value(want)
			p.state = want
		end
	end
end

-- Env PROBE_WORDS: comma list of hex DGROUP offsets dumped at each snapshot.
-- DS is the most frequent DS0 seen by the periodic callback since the last
-- snapshot; addresses go through the live PGR table when XA is on.
local words = {}
for w in string.gmatch(os.getenv("PROBE_WORDS") or "", "[^,]+") do
	words[#words + 1] = tonumber(w, 16)
end
local wordlog = #words > 0 and io.open(out .. "/ram_words.log", "w") or nil
local prog = cpu.spaces["program"]
local ds_hist = {}

local function phys(seg, off)
	local a = ((seg << 4) + off) & 0xfffff
	if cpu.state["XA"].value ~= 0 then
		local pgr = iosp:read_u16(0xff00 + ((a >> 14) & 0x3f) * 2)
		return ((pgr & 0x3ff) << 14) | (a & 0x3fff)
	end
	return a
end

local function dump_words(t)
	local ds, best = 0, -1
	for v, n in pairs(ds_hist) do
		if n > best then ds, best = v, n end
	end
	wordlog:write(string.format("@ %.3f DS=%04X (%d samples) XA=%d\n", t, ds, best, cpu.state["XA"].value))
	for _, off in ipairs(words) do
		wordlog:write(string.format("%04X %04X\n", off, prog:read_u16(phys(ds, off))))
	end
	wordlog:flush()
	ds_hist = {}
end

local idx = 1
emu.register_periodic(function()
	drive_inputs()
	if wordlog then
		local ds = cpu.state["DS0"].value
		ds_hist[ds] = (ds_hist[ds] or 0) + 1
	end
	-- V53 OPSEL/xULA writes reinstall I/O handlers, which can drop taps.
	lcd_tap:reinstall()
	rtap:reinstall()
	wtap:reinstall()
	for _, t in ipairs(traced) do
		t:reinstall()
	end
	if idx <= #times and now() >= times[idx] then
		dump_text(times[idx])
		if wordlog then dump_words(times[idx]) end
		machine.video:snapshot()
		lcdlog:flush()
		portlog:flush()
		tracelog:flush()
		idx = idx + 1
		if idx > #times then
			machine:exit()
		end
	end
end)

probe_keep_alive = { lcd_tap, rtap, wtap, traced }
