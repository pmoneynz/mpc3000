-- Evidence probe for the WAVE <Ply/Stp> path.
--
-- Record every read of sound record zero's start/end dwords with the reader's
-- CS:IP.  Reads by the stock player CFC6:0CE9 (CS=CFC6, IP in [0CE9,0D75))
-- are the proof that the player consumed the bounds (instruction-fetch taps are not
-- exposed by this MAME build, so an entry tap would see nothing).  Also
-- reconstruct the L7A1045's 48-bit DSP start register from full 16-bit I/O
-- writes, identify stock D213 releases and D21F channel stops at their exact
-- OUT instructions, log writes/restored snapshots of sound record zero, and
-- optionally record short WAV windows of the mixed output.
--
-- Runtime address mode is XA=1 with the third PGR (Route A, both profiles).
-- The record is RAM at A2AE:4800 (physical 0x3A72E0), so its bounds are
-- physical 0x3A72F4..0x3A72FB.
--
-- Env: PLAYBACK_WATCH_FROM (emulated s) starts BOUNDWRITE/BOUNDREAD logging
-- after the SND load; PLAYBACK_WAV is "start:stop:file;..." windows recorded
-- with machine.sound:start_recording (WAVSTART/WAVSTOP give the exact times).

local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local iosp = cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/wave_playback.log", "w"))

local function now()
	return machine.time:as_double()
end

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

local function rd8(seg, off)
	return prog:read_u8(phys(seg, off))
end

local function rd16(seg, off)
	return rd8(seg, off) | (rd8(seg, off + 1) << 8)
end

local function rd32(seg, off)
	return rd16(seg, off) | (rd16(seg, off + 2) << 16)
end

local function record(kind, t)
	log:write(string.format(
		"%s t=%.6f start=%u end=%u len=%u wave=%08X\n",
		kind, t, rd32(0xa2ae, 0x4814), rd32(0xa2ae, 0x4818),
		rd32(0xa2ae, 0x481c), rd32(0xa2ae, 0x4820)))
	log:flush()
end

local watch_from = tonumber(os.getenv("PLAYBACK_WATCH_FROM") or "0")

-- Every word read of the record-zero bounds, with the reader's CS:IP.  The
-- tests pick out the stock player body (CFC6, IP in [0CE9,0D75)).  The Lua
-- observers' own read_u8 calls also trigger this tap (as byte lanes, with
-- whatever CS:IP the CPU happens to be at), so only full-word reads, the
-- form the player uses, are logged.
local read_tap = prog:install_read_tap(0x3a72f4, 0x3a72fb, "wave_bound_read", function(offset, data, mask)
	if now() < watch_from then return end
	local cs, ip = csip()
	if mask & 0xffff == 0xffff then
		log:write(string.format("BOUNDREAD t=%.6f cs=%04X ip=%04X phys=%06X data=%04X mask=%04X\n",
			now(), cs, ip, offset, data & 0xffff, mask & 0xffff))
		log:flush()
	end
end)

-- These eight bytes are the start/end dwords of record zero.  Playback tests
-- load exactly one sound, so every audition mutation and restoration lands
-- here.  The tap provides the writer CS:IP and the complete 16-bit bus value.
local bounds_tap = prog:install_write_tap(0x3a72f4, 0x3a72fb, "wave_bounds", function(offset, data, mask)
	if now() >= watch_from then
		local cs, ip = csip()
		log:write(string.format(
			"BOUNDWRITE t=%.6f cs=%04X ip=%04X phys=%06X data=%04X mask=%04X\n",
			now(), cs, ip, offset, data & 0xffff, mask & 0xffff))
		log:flush()
	end
end)

-- Mirror the DSP's three 16-bit lanes per register/channel.  Unlike the
-- generic byte trace, this preserves both bytes of every OUT DX,AX.
local selected_channel, selected_reg = 0, 0
local regs = {}
local function lanes(reg, channel)
	regs[reg] = regs[reg] or {}
	regs[reg][channel] = regs[reg][channel] or {0, 0, 0}
	return regs[reg][channel]
end
local function merge(old, data, mask)
	return ((old & (~mask & 0xffff)) | (data & mask)) & 0xffff
end

local dsp_tap = iosp:install_write_tap(0x60, 0x6f, "wave_dsp", function(offset, data, mask)
	local cs, ip = csip()
	if offset == 0x60 then
		if mask & 0x00ff ~= 0 then selected_channel = data & 0x1f end
		if mask & 0xff00 ~= 0 then selected_reg = (data >> 8) & 0x0f end
		-- D21F:001C is OUT DX,AX with AX = 0x0400 + channel (register 4
		-- select); D213:001B is the release's register select.  Match the
		-- instruction and its full-word operand form, not just CS:IP.
		if cs == 0xd21f and ip == 0x001c and mask == 0xffff and (data >> 8) & 0xff == 0x04 then
			log:write(string.format("D21F t=%.6f ch=%u data=%04X mask=%04X\n",
				now(), data & 0x1f, data & 0xffff, mask & 0xffff))
		elseif cs == 0xd213 and ip == 0x001b and mask == 0xffff and (data >> 8) & 0xff == 0x04 then
			log:write(string.format("D213 t=%.6f ch=%u data=%04X mask=%04X\n",
				now(), data & 0x1f, data & 0xffff, mask & 0xffff))
		end
	elseif offset >= 0x62 and offset <= 0x66 then
		local lane = (offset - 0x62) // 2 + 1
		local value = lanes(selected_reg, selected_channel)
		value[lane] = merge(value[lane], data, mask)
		if selected_reg == 0 and cs == 0xd1f7 and ip == 0x0054 then
			local raw = value[1] | (value[2] << 16) | (value[3] << 32)
			log:write(string.format(
				"STARTREG t=%.6f cs=%04X ip=%04X ch=%u start=%06X type=%X mask=%04X\n",
				now(), cs, ip, selected_channel, (raw >> 12) & 0xffffff,
				(raw >> 36) & 0x0f, mask & 0xffff))
		end
	elseif offset == 0x68 and data & mask & 0x0100 ~= 0 then
		local start = lanes(0, selected_channel)
		local step = lanes(1, selected_channel)[1]
		local mixer = lanes(7, selected_channel)
		local start48 = start[1] | (start[2] << 16) | (start[3] << 32)
		local mix32 = mixer[1] | (mixer[2] << 16)
		log:write(string.format(
			"KEYON t=%.6f cs=%04X ip=%04X ch=%u start=%06X type=%X step=%04X mixer=%08X left=%02X right=%02X\n",
			now(), cs, ip, selected_channel, (start48 >> 12) & 0xffffff,
			(start48 >> 36) & 0x0f, step, mix32, (mix32 >> 8) & 0xff, mix32 & 0xff))
	end
	log:flush()
end)

local snapshots = {}
for value in string.gmatch(os.getenv("PLAYBACK_SNAPSHOTS") or os.getenv("PROBE_TIMES") or "", "[^,]+") do
	snapshots[#snapshots + 1] = tonumber(value)
end
local snapshot_index = 1

emu.register_periodic(function()
	read_tap:reinstall()
	bounds_tap:reinstall()
	dsp_tap:reinstall()
	if snapshot_index <= #snapshots and now() >= snapshots[snapshot_index] then
		record("SNAP", snapshots[snapshot_index])
		snapshot_index = snapshot_index + 1
	end
end)

-- Short WAV windows instead of a whole-run -wavwrite file.
local windows = {}
for item in string.gmatch(os.getenv("PLAYBACK_WAV") or "", "[^;]+") do
	local a, b, f = string.match(item, "^([^:]+):([^:]+):(.+)$")
	windows[#windows + 1] = { start = tonumber(a), stop = tonumber(b), file = f, state = 0 }
end
emu.register_periodic(function()
	local t = now()
	for _, w in ipairs(windows) do
		if w.state == 0 and t >= w.start then
			local ok = machine.sound:start_recording(out .. "/" .. w.file)
			log:write(string.format("WAVSTART t=%.6f file=%s ok=%d\n", t, w.file, ok and 1 or 0))
			w.state = 1
		elseif w.state == 1 and t >= w.stop then
			machine.sound:stop_recording()
			log:write(string.format("WAVSTOP t=%.6f file=%s\n", t, w.file))
			w.state = 2
		end
	end
	log:flush()
end)

wave_playback_keep_alive = {read_tap, bounds_tap, dsp_tap}
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
