-- mute_voice.lua for the 316 profile (WAVE316.SYS on OS 3.16, Route C).
--
-- The harness preamble defines MUTE_VOICE_OFFSETS (the assembled map),
-- CAVE_SEG / CAVE_PHYS (the cave at its home, L+7E00 = physical
-- 0x300000 + L*16 + 0x7E000) and LOAD_SEG (L).  Same output as
-- mute_voice.lua: mute_voice.log with SNAP, TAGWRITE, STOP and KEYON lines.
-- This script installs taps and reads live state; it never writes MPC RAM.

local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local iosp = cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/mute_voice.log", "w"))
local off = assert(MUTE_VOICE_OFFSETS, "generated preamble lacks MUTE_VOICE_OFFSETS")

-- The one-channel stop T_D21F_0008 is 3.16 relative 234D:0000
-- (mods/profile_316.inc).  Its first register-select OUT DX,AX (AX = 0x0400 +
-- channel) is at 234D:0014 (image 0x234E4), as D21F:001C is in Vailixi: the
-- 41 instructions from the entry match one for one (only the far call to
-- the resource reservation differs), so the frame is the same.
local STOP_CS, STOP_IP = (LOAD_SEG + 0x234D) & 0xffff, 0x0014

local function now()
	return machine.time:as_double()
end

local function csip()
	local cs = tonumber(cpu.state["PS"].value)
	return cs, (cpu.state["CURPC"].value - (cs << 4)) & 0xffff
end

local function phys(seg, offset)
	local a = ((seg << 4) + offset) & 0xfffff
	if cpu.state["XA"].value ~= 0 then
		local pgr = iosp:read_u16(0xff00 + ((a >> 14) & 0x3f) * 2)
		return ((pgr & 0x3ff) << 14) | (a & 0x3fff)
	end
	return a
end

local function rd8(seg, offset)
	return prog:read_u8(phys(seg, offset))
end

local function rd16(seg, offset)
	return rd8(seg, offset) | (rd8(seg, (offset + 1) & 0xffff) << 8)
end

local function snapshot(t)
	local tags = {}
	for ch = 0, 31 do
		local program = rd8(CAVE_SEG, off.mute_voice_program + ch)
		local pad = rd8(CAVE_SEG, off.mute_voice_pad + ch)
		if program ~= 0 then
			tags[#tags + 1] = string.format("%u:%u:%u", ch, program, pad)
		end
	end
	local packed = #tags == 0 and "-" or table.concat(tags, ",")
	log:write(string.format(
		"SNAP t=%.6f tags=%s valid=%u program=%u pad=%u group=%u\n",
		t, packed, rd8(CAVE_SEG, off.mute_context_valid),
		rd8(CAVE_SEG, off.mute_context_program), rd8(CAVE_SEG, off.mute_context_pad),
		rd8(CAVE_SEG, off.mute_context_group)))
	log:flush()
end

-- Sidecar writes provide exact tag lifetime and the writer responsible.
local function tag_tap(name, offset)
	local first = CAVE_PHYS + offset
	local last = first + 31
	return prog:install_write_tap(first & ~1, last | 1,
		"mute_" .. name, function(address, data, mask)
			local cs, ip = csip()
			for lane = 0, 1 do
				local lane_mask = 0xff << (lane * 8)
				local byte_address = address + lane
				if mask & lane_mask ~= 0 and byte_address >= first and byte_address <= last then
					log:write(string.format(
						"TAGWRITE t=%.6f table=%s ch=%u value=%02X mask=%04X cs=%04X ip=%04X\n",
						now(), name, byte_address - first,
						(data >> (lane * 8)) & 0xff, lane_mask, cs, ip))
				end
			end
			log:flush()
		end)
end

local program_tap = tag_tap("program", off.mute_voice_program)
local pad_tap = tag_tap("pad", off.mute_voice_pad)

-- Mirror the DSP register selection so key-ons can be counted by channel.
-- The stop's first register-select write occurs with its BP frame live,
-- allowing the caller CS:IP and channel argument to be recorded without
-- fetch taps.
local selected_channel, selected_reg = 0, 0
local dsp_tap = iosp:install_write_tap(0x60, 0x6f, "mute_dsp", function(address, data, mask)
	local cs, ip = csip()
	if address == 0x60 then
		if mask & 0x00ff ~= 0 then selected_channel = data & 0x1f end
		if mask & 0xff00 ~= 0 then selected_reg = (data >> 8) & 0x0f end
		local t = now()
		-- Match the instruction and its full-word operand, as mute_voice.lua
		-- does, not merely any port-60 write at that CS:IP.
		if cs == STOP_CS and ip == STOP_IP and mask == 0xffff and (data >> 8) & 0xff == 0x04 then
			local ss = tonumber(cpu.state["SS"].value)
			-- The stop has pushed BP and copied SP into it by its first OUT.
			-- MAME exposes SP but not BP in this V53 state surface, so SP is
			-- the live frame base here.
			local bp = tonumber(cpu.state["SP"].value)
			log:write(string.format(
				"STOP t=%.6f ch=%u caller_cs=%04X caller_ip=%04X arg=%u stop_ip=%04X\n",
				t, data & 0x1f, rd16(ss, (bp + 4) & 0xffff),
				rd16(ss, (bp + 2) & 0xffff), rd16(ss, (bp + 6) & 0xffff), ip))
		end
	elseif address == 0x68 and data & mask & 0x0100 ~= 0 then
		log:write(string.format("KEYON t=%.6f ch=%u cs=%04X ip=%04X\n",
			now(), selected_channel, cs, ip))
	end
	log:flush()
end)

local snapshots = {}
for value in string.gmatch(os.getenv("MUTE_SNAPSHOTS") or os.getenv("PROBE_TIMES") or "", "[^,]+") do
	snapshots[#snapshots + 1] = tonumber(value)
end
local snapshot_index = 1

emu.register_periodic(function()
	program_tap:reinstall()
	pad_tap:reinstall()
	dsp_tap:reinstall()
	if snapshot_index <= #snapshots and now() >= snapshots[snapshot_index] then
		snapshot(snapshots[snapshot_index])
		snapshot_index = snapshot_index + 1
	end
end)

mute_voice_keep_alive = {program_tap, pad_tap, dsp_tap}
