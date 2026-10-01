-- Evidence probe for the WAVE <Play X> path.
--
-- At each CFC6:0CE9 entry, record the exact sound-directory bounds consumed
-- by the stock player.  Also reconstruct the L7A1045's 48-bit DSP start
-- register from full 16-bit I/O writes, identify stock D21F channel stops,
-- and log writes/restored snapshots of sound record zero.
--
-- Runtime address mode is XA=1 with the third PGR table.  The execution tap
-- therefore names the 24-bit physical CE9 address, 0x3D0949, rather than the
-- 20-bit address 0xD0949.  The record is RAM at A2AE:4800 (physical 0x3A72E0).

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

-- A program-space read tap sees V53 instruction prefetches.  Restrict the
-- callback further with live CS:IP so data reads in the same physical range
-- cannot be mistaken for a player call.
local last_ce9 = -1
local ce9_tap = prog:install_read_tap(0x3d0948, 0x3d0951, "wave_ce9", function(offset, data, mask)
	local cs, ip = csip()
	local t = now()
	-- The first aligned prefetch word contains entry byte 0x3D0949.  CURPC's
	-- Lua wrapper is useful for reporting, but the translated fetch address is
	-- the reliable executed-entry discriminator.
	if cs == 0xcfc6 and tonumber(offset) == 0x3d0948 and t - last_ce9 > 0.000001 then
		last_ce9 = t
		local ss, sp = tonumber(cpu.state["SS0"].value), tonumber(cpu.state["SP"].value)
		local index = rd16(ss, (sp + 4) & 0xffff)
		log:write(string.format(
			"CE9 t=%.6f cs=%04X ip=%04X phys=3D0949 index=%u start=%u end=%u len=%u wave=%08X xa=%u\n",
			t, cs, ip, index, rd32(0xa2ae, 0x4814), rd32(0xa2ae, 0x4818),
			rd32(0xa2ae, 0x481c), rd32(0xa2ae, 0x4820), cpu.state["XA"].value))
		log:flush()
	end
end)

-- These eight bytes are the start/end dwords of record zero.  Playback tests
-- load exactly one sound, so every audition mutation and restoration lands
-- here.  The tap provides the writer CS:IP and the complete 16-bit bus value.
local bounds_tap = prog:install_write_tap(0x3a72f4, 0x3a72fb, "wave_bounds", function(offset, data, mask)
	if now() >= 79.0 then
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
		if cs == 0xd21f and ip == 0x001c then
			log:write(string.format("D21F t=%.6f ch=%u data=%04X mask=%04X\n",
				now(), data & 0x1f, data & 0xffff, mask & 0xffff))
		elseif cs == 0xd213 and ip == 0x001b then
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
	ce9_tap:reinstall()
	bounds_tap:reinstall()
	dsp_tap:reinstall()
	if snapshot_index <= #snapshots and now() >= snapshots[snapshot_index] then
		record("SNAP", snapshots[snapshot_index])
		snapshot_index = snapshot_index + 1
	end
end)

wave_playback_keep_alive = {ce9_tap, bounds_tap, dsp_tap}
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
