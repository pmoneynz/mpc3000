-- mute_voice.lua for the 316 profile (WAVE316.SYS on OS 3.16, Route C).
-- The harness preamble (emu/harness.py observer()) defines CAVE (assembled
-- map offsets), LOAD_SEG (L), CAVE_SEG (L+7E00) and CAVE_PHYS (0x300000 +
-- L*16 + 0x7E000).  Same output as mute_voice.lua: mute_voice.log with
-- TAGWRITE, STOP, KEYON and SNAP lines.  Installs taps and reads live state;
-- it never writes MPC RAM.

local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local iosp = cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/mute_voice.log", "w"))
local off = CAVE

-- One-channel stop T_D21F_0008 = 3.16 234D:0000 (mods/profile_316.inc).  Its
-- bytes equal Vailixi D21F:0008..0047 except the relocated reserve call, so
-- D21F:001C (OUT DX,AX, AX = 0400h + channel) is 234D:0014 at CS = L+234D.
local STOP_CS = (LOAD_SEG + 0x234D) & 0xffff
local STOP_IP = 0x0014

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

-- Tag writes at the cave home, with the writer's CS:IP (the entry routine's
-- copy writes them too, from the staging segment).
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
-- 234D:0000 pushes BP and copies SP into it; its reserve call has returned by
-- the OUT at 0014, so SP is the frame base there (MAME exposes SP, not BP).
local selected_channel = 0
local dsp_tap = iosp:install_write_tap(0x60, 0x6f, "mute_dsp", function(address, data, mask)
	local cs, ip = csip()
	if address == 0x60 then
		if mask & 0x00ff ~= 0 then selected_channel = data & 0x1f end
		if cs == STOP_CS and ip == STOP_IP and mask == 0xffff and (data >> 8) & 0xff == 0x04 then
			local ss = tonumber(cpu.state["SS"].value)
			local bp = tonumber(cpu.state["SP"].value)
			log:write(string.format(
				"STOP t=%.6f ch=%u caller_cs=%04X caller_ip=%04X arg=%u stop_ip=%04X\n",
				now(), data & 0x1f, rd16(ss, (bp + 4) & 0xffff),
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
	if snapshot_index <= #snapshots and now() >= snapshots[snapshot_index] then
		snapshot(snapshots[snapshot_index])
		snapshot_index = snapshot_index + 1
	end
end)

mute_voice_keep_alive = {program_tap, pad_tap, dsp_tap}
