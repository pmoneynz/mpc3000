-- LCD mirror (mods/lcdmirror316.asm): how long each tick spends in the cave with
-- IF = 0.  An opcode-fetch tap on lm_tick (the cave home, LM_TICK_PHYS) marks the
-- entry; the next fetch of the tick handler's IRET 2B50:0061 (LM_IRET_PHYS) marks
-- the return through the AMX exit.  Prefetch of the IRET byte happens before the
-- CALLF to the cave, so only fetches after an entry count.  Writes
-- lcdmirror_cost.txt in PROBE_OUT: per tick "t us", then a summary.  Read-only.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local out = os.getenv("PROBE_OUT") or "."
local entry_phys = tonumber(os.getenv("LM_TICK_PHYS"), 16)
local iret_phys = tonumber(os.getenv("LM_IRET_PHYS"), 16)
local entered = nil
local log = io.open(out .. "/lcdmirror_cost.txt", "w")
local n, total, max, max_t = 0, 0, 0, 0
local function on_entry(offset, data, mask)
	entered = machine.time:as_double()
end
local function on_iret(offset, data, mask)
	if entered then
		local now = machine.time:as_double()
		local us = (now - entered) * 1e6
		entered = nil
		n, total = n + 1, total + us
		if us > max then max, max_t = us, now end
		log:write(string.format("%.6f %.2f\n", now, us))
	end
end
lmcost_keep = {
	prog:install_read_tap(entry_phys, entry_phys + 1, "lm_entry", on_entry),
	prog:install_read_tap(iret_phys & ~1, (iret_phys & ~1) + 1, "lm_iret", on_iret),
}
emu.register_periodic(function()
	if n > 0 then
		local f = io.open(out .. "/lcdmirror_cost_summary.txt", "w")
		f:write(string.format("ticks %d mean_us %.2f max_us %.2f max_at %.6f\n", n, total / n, max, max_t))
		f:close()
		log:flush()
	end
end)
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
