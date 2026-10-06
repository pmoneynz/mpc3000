-- Count every read (data or opcode fetch) and write of the code cave, file
-- 0x707C8-0x73FFF, at its two physical homes: EPROM 0xF07C8 and the Route A
-- RAM copy (logical page 60 -> physical page 0x0FC). Writes cave.txt in
-- PROBE_OUT, with the first accesses of each kind. Then runs the normal probe.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local out = os.getenv("PROBE_OUT") or "."
local count, first = {}, {}
local function tap(key)
	return function(offset, data, mask)
		count[key] = (count[key] or 0) + 1
		if count[key] <= 8 then
			local ps = cpu.state["PS"].value
			first[#first + 1] = string.format("%.6f %04X:%04X %s %06X", machine.time:as_double(), ps,
				(cpu.state["CURPC"].value - (ps << 4)) & 0xffff, key, offset)
		end
	end
end
local taps = {}
for _, lo in ipairs({0xF07C8, 0x3F07C8}) do
	local hi = lo | 0x3FFF
	taps[#taps + 1] = prog:install_read_tap(lo, hi, "cave_r", tap(string.format("R%06X", lo)))
	taps[#taps + 1] = prog:install_write_tap(lo, hi, "cave_w", tap(string.format("W%06X", lo)))
end
cave_keep = taps
local last = -1
emu.register_periodic(function()
	local n = #first
	for _, v in pairs(count) do n = n + v end
	if n ~= last then
		last = n
		local f = io.open(out .. "/cave.txt", "w")
		for _, k in ipairs({"RF07C8", "WF07C8", "R3F07C8", "W3F07C8"}) do
			f:write(string.format("%s %d\n", k, count[k] or 0))
		end
		f:write(table.concat(first, "\n"), "\n")
		f:close()
	end
end)
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
