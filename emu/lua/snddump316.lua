-- snddump.lua for the 316 profile: the sound directory is SND_SEG:4800
-- (runtime L+539D, defined by the harness preamble), 128 x 24h records, same
-- format and output files as snddump.lua (snd_dir.log, wave_<t>_idx<i>.bin;
-- SNDDUMP_PCM as there).  Read-only.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local iosp = cpu.spaces["io"]
local prog = cpu.spaces["program"]
local wave
for k, v in pairs(machine.devices[":dsp"].spaces) do
	if not wave and not string.find(k, "rom") then wave = v end
end
local out = os.getenv("PROBE_OUT") or "."
local times = {}
for t in string.gmatch(os.getenv("PROBE_TIMES") or "", "[^,]+") do times[#times + 1] = tonumber(t) end
local log = io.open(out .. "/snd_dir.log", "w")
local pcm_spec = os.getenv("SNDDUMP_PCM") or "1"
local pcm_times = nil
if pcm_spec ~= "0" and pcm_spec ~= "1" then
	pcm_times = {}
	for v in string.gmatch(pcm_spec, "[^,]+") do pcm_times[#pcm_times + 1] = tonumber(v) end
end
local function want_pcm_at(t)
	if pcm_spec == "0" then return false end
	if not pcm_times then return true end
	for _, v in ipairs(pcm_times) do
		if math.abs(v - t) < 0.0005 then return true end
	end
	return false
end

local function phys(seg, off)
	local a = ((seg << 4) + off) & 0xfffff
	if cpu.state["XA"].value ~= 0 then
		return ((iosp:read_u16(0xff00 + (a >> 14) * 2) & 0x3ff) << 14) | (a & 0x3fff)
	end
	return a
end
local function rd8(off) return prog:read_u8(phys(SND_SEG, off)) end
local function rd32(off) return rd8(off) | (rd8(off + 1) << 8) | (rd8(off + 2) << 16) | (rd8(off + 3) << 24) end

local function dump(t)
	local want_pcm = want_pcm_at(t)
	log:write(string.format("@ %.3f\n", t))
	for i = 0, 127 do
		local o = 0x4800 + i * 0x24
		if rd8(o) ~= 0 then
			local name = {}
			for k = 0, 16 do local c = rd8(o + k); if c == 0 then break end; name[#name + 1] = string.char(c) end
			local st, len, wa = rd8(o + 0x13), rd32(o + 0x1c), rd32(o + 0x20)
			log:write(string.format("idx %d name='%s' vol=%d stereo=%d start=%d end=%d len=%d wave=%08X\n",
				i, table.concat(name), rd8(o + 0x11), st, rd32(o + 0x14), rd32(o + 0x18), len, wa))
			local words = len * (st + 1)
			if want_pcm and words > 0 and words < 0x400000 then
				local f = io.open(string.format("%s/wave_%g_idx%d.bin", out, t, i), "wb")
				local buf = {}
				for w = 0, words - 1 do
					buf[#buf + 1] = string.pack("<I2", wave:read_u16(((wa + w) * 2) & 0x1ffffff))
					if #buf == 4096 then f:write(table.concat(buf)); buf = {} end
				end
				f:write(table.concat(buf))
				f:close()
			end
		end
	end
	log:flush()
end

local idx = 1
emu.register_periodic(function()
	if idx <= #times and machine.time:as_double() >= times[idx] - 0.05 then
		dump(times[idx])
		idx = idx + 1
	end
end)
