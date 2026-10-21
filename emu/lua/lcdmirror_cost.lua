-- LCD mirror (mods/lcdmirror316.asm) cost probe: logs the emulated time of every
-- opcode fetch of a list of physical addresses, LM_POINTS="name=HEX,name=HEX,...".
-- emu/lcdmirror_cost.py turns the log into per-tick interrupt-off windows and
-- time in the cave.  Prefetch makes a hit up to a few cycles early.  Read-only.
-- Writes lcdmirror_cost.txt in PROBE_OUT ("t name" per hit).
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local out = os.getenv("PROBE_OUT") or "."
local log = io.open(out .. "/lcdmirror_cost.txt", "w")
lmcost_keep = {}
for name, hex in string.gmatch(os.getenv("LM_POINTS") or "", "([%w_]+)=(%x+)") do
	local a = tonumber(hex, 16)
	local word = a & ~1
	local odd = a & 1
	lmcost_keep[#lmcost_keep + 1] = prog:install_read_tap(word, word + 1, "lm_" .. name, function(offset, data, mask)
		if odd == 0 and (mask & 0xff) == 0 then return end
		if odd == 1 and (mask & 0xff00) == 0 then return end
		log:write(string.format("%.7f %s\n", machine.time:as_double(), name))
	end)
end
emu.register_periodic(function() log:flush() end)
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
