-- Read back the V53 wait control and refresh registers once the OS has
-- programmed them (wcu.txt: one "FFxx=vv" per line). Then run the normal probe.
local out = os.getenv("PROBE_OUT") or "."
local iosp = manager.machine.devices[":maincpu"].spaces["io"]
local done = false
emu.register_periodic(function()
	if done or manager.machine.time:as_double() < 1.0 then return end
	done = true
	local f = io.open(out .. "/wcu.txt", "w")
	for _, port in ipairs({ 0xffea, 0xffeb, 0xffec, 0xffed, 0xfff2, 0xfff3, 0xfff4, 0xfff5, 0xfff6 }) do
		f:write(string.format("%04X=%02X\n", port, iosp:read_u8(port)))
	end
	f:close()
end)
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
