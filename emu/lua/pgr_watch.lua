-- Print the V33 page table (io 0xFF00) whenever pages 44-60 change, and the
-- byte at logical B000:0207 through that table. Then run the normal probe.
local cpu = manager.machine.devices[":maincpu"]
local iosp = cpu.spaces["io"]
local prog = cpu.spaces["program"]
local last = ""
emu.register_periodic(function()
	local w = {}
	for p = 44, 60 do w[#w + 1] = string.format("%03X", iosp:read_u16(0xff00 + 2 * p)) end
	local s = table.concat(w, " ")
	if s ~= last then
		local a = 0xB0207
		local b = prog:read_u8((iosp:read_u16(0xff00 + 2 * (a >> 14)) << 14) | (a & 0x3fff))
		print(string.format("PGR t=%.3f pages44-60=%s B000:0207=%02X", manager.machine.time:as_double(), s, b))
		last = s
	end
end)
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
