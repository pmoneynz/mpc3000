-- Test injection for emu/test_pmoney_noteon.py: at PADMODE_AT (emulated s)
-- write 1 to the pad-table mode byte at physical PADMODE_PHYS and the 64
-- bytes of PADMODE_TABLE (hex) after it, so the stock pad lookup and the
-- cave's both read the alternate table.  It writes nothing else.
local machine = manager.machine
local prog = machine.devices[":maincpu"].spaces["program"]
local at = tonumber(os.getenv("PADMODE_AT"))
local base = tonumber(os.getenv("PADMODE_PHYS"), 16)
local tbl = os.getenv("PADMODE_TABLE")
local done = false
emu.register_periodic(function()
	if not done and machine.time:as_double() >= at then
		prog:write_u8(base, 1)
		for i = 0, 63 do
			prog:write_u8(base + 1 + i, tonumber(tbl:sub(2 * i + 1, 2 * i + 2), 16))
		end
		done = true
	end
end)
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
