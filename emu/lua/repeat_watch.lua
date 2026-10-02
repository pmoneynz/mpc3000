-- Read-only observer of the normalized-key repeat count as the cave consumes it.
--
-- The harness preamble (emu/harness.py observer()) defines CAVE (assembled map
-- offsets) and DG (profile DGROUP offsets).  WAVE copies the stock count
-- (D6E0:001B writes DGROUP D69A generic / D698 capture) into its CS-relative
-- word key_repeat after every BDE3:000E key; the mute page copies it into
-- mu_repeat.  Every write of those two cave words is logged with its value:
-- one line per key the cave processed.  The cave runs in the Route A RAM copy,
-- F07D:0000 = physical 0x3F07D0 (XA=1, third PGR) in both profiles.
-- repeat.log also records the stock key-queue capacity (DGROUP queue +0).
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, iosp = cpu.spaces["program"], cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/repeat.log", "w"))
local CAVE_PHYS = 0x3f07d0

local function phys(seg, off)
	local a = ((seg << 4) + off) & 0xfffff
	if cpu.state["XA"].value ~= 0 then
		return ((iosp:read_u16(0xff00 + ((a >> 14) & 0x3f) * 2) & 0x3ff) << 14) | (a & 0x3fff)
	end
	return a
end

local taps = {}
for _, name in ipairs({ "key_repeat", "mu_repeat" }) do
	local off = CAVE[name]
	if off then
		local first = CAVE_PHYS + off
		taps[#taps + 1] = prog:install_write_tap(first & ~1, (first + 1) | 1, "rep_" .. name,
			function(address, data, mask)
				local value
				if first & 1 == 0 and mask == 0xffff then
					value = data & 0xffff
				else
					value = -1          -- not the single aligned word write expected
				end
				log:write(string.format("REPEAT t=%.6f sym=%s value=%d mask=%04X\n",
					machine.time:as_double(), name, value, mask & 0xffff))
				log:flush()
			end)
	end
end

local queue_logged = false
emu.register_periodic(function()
	for _, t in ipairs(taps) do t:reinstall() end
	if not queue_logged and machine.time:as_double() >= 20.0 and cpu.state["XA"].value ~= 0 then
		log:write(string.format("QUEUE t=%.6f capacity=%d\n", machine.time:as_double(),
			prog:read_u16(phys(0x8010, DG.key_queue))))
		log:flush()
		queue_logged = true
	end
end)
repeat_watch_keep_alive = taps
