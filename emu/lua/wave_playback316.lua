-- wave_playback.lua for the 316 profile (WAVE316.SYS on OS 3.16, Route C).
-- Same output (wave_playback.log: BOUNDREAD, BOUNDWRITE, STARTREG, KEYON,
-- D213, D21F, SNAP, WAVSTART/WAVSTOP) and environment (PLAYBACK_WATCH_FROM,
-- PLAYBACK_SNAPSHOTS, PLAYBACK_WAV) as wave_playback.lua.  Read-only.
--
-- Addresses: record zero is SND_SEG:4800 (runtime L+539D, harness preamble),
-- its start/end dwords at SND_PHYS..SND_PHYS+7 (third PGR: physical =
-- 0x300000 + logical; checked through the live PGR at 33 s).  cs/ip in the
-- log are runtime values (CS = L + relative segment).  The three stock OUT
-- instructions the Vailixi part matches by CS:IP, in 3.16 relative seg:off
-- (instruction-identical windows; callers in the same modules):
--   D1F7:0054 -> 2325:004C  start register lane 0 (OUT 62h) in 2325:0006,
--                           whose only far caller is the player at 20ED:0BA6
--                           (Vailixi D1F7:000E, called from CFC6:0BA0)
--   D213:001B -> 2341:0013  release register select (AX = 0400h + channel)
--                           in 2341:0000 (Vailixi D213:0008)
--   D21F:001C -> 234D:0014  stop register select in 234D:0000 (profile_316.inc
--                           T_D21F_0008)
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local iosp = cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/wave_playback.log", "w"))

local START_CS, START_IP = (LOAD_SEG + 0x2325) & 0xffff, 0x004c
local RELEASE_CS, RELEASE_IP = (LOAD_SEG + 0x2341) & 0xffff, 0x0013
local STOP_CS, STOP_IP = (LOAD_SEG + 0x234d) & 0xffff, 0x0014
local SND_PHYS = 0x300000 + SND_SEG * 16 + 0x4814

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
		kind, t, rd32(SND_SEG, 0x4814), rd32(SND_SEG, 0x4818),
		rd32(SND_SEG, 0x481c), rd32(SND_SEG, 0x4820)))
	log:flush()
end

local watch_from = tonumber(os.getenv("PLAYBACK_WATCH_FROM") or "0")

-- Full-word reads of the record-zero bounds with the reader's CS:IP (the
-- observers' own byte reads are excluded by the mask, as in wave_playback.lua).
local read_tap = prog:install_read_tap(SND_PHYS, SND_PHYS + 7, "wave_bound_read", function(offset, data, mask)
	if now() < watch_from then return end
	local cs, ip = csip()
	if mask & 0xffff == 0xffff then
		log:write(string.format("BOUNDREAD t=%.6f cs=%04X ip=%04X phys=%06X data=%04X mask=%04X\n",
			now(), cs, ip, offset, data & 0xffff, mask & 0xffff))
		log:flush()
	end
end)

local bounds_tap = prog:install_write_tap(SND_PHYS, SND_PHYS + 7, "wave_bounds", function(offset, data, mask)
	if now() >= watch_from then
		local cs, ip = csip()
		log:write(string.format(
			"BOUNDWRITE t=%.6f cs=%04X ip=%04X phys=%06X data=%04X mask=%04X\n",
			now(), cs, ip, offset, data & 0xffff, mask & 0xffff))
		log:flush()
	end
end)

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
		if cs == STOP_CS and ip == STOP_IP and mask == 0xffff and (data >> 8) & 0xff == 0x04 then
			log:write(string.format("D21F t=%.6f ch=%u data=%04X mask=%04X\n",
				now(), data & 0x1f, data & 0xffff, mask & 0xffff))
		elseif cs == RELEASE_CS and ip == RELEASE_IP and mask == 0xffff and (data >> 8) & 0xff == 0x04 then
			log:write(string.format("D213 t=%.6f ch=%u data=%04X mask=%04X\n",
				now(), data & 0x1f, data & 0xffff, mask & 0xffff))
		end
	elseif offset >= 0x62 and offset <= 0x66 then
		local lane = (offset - 0x62) // 2 + 1
		local value = lanes(selected_reg, selected_channel)
		value[lane] = merge(value[lane], data, mask)
		if selected_reg == 0 and cs == START_CS and ip == START_IP then
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
local pgr_checked = false

emu.register_periodic(function()
	read_tap:reinstall()
	bounds_tap:reinstall()
	dsp_tap:reinstall()
	if not pgr_checked and now() >= 33.0 and cpu.state["XA"].value ~= 0 then
		-- The taps assume physical = 0x300000 + logical for the record.
		if phys(SND_SEG, 0x4814) ~= SND_PHYS then
			log:write(string.format("SNDPHYS t=%.6f mismatch=%d\n", now(), phys(SND_SEG, 0x4814)))
		end
		pgr_checked = true
	end
	if snapshot_index <= #snapshots and now() >= snapshots[snapshot_index] then
		record("SNAP", snapshots[snapshot_index])
		snapshot_index = snapshot_index + 1
	end
end)

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
