-- repeat_watch.lua for the 316 profile.  The cave copies 3.16's key repeat
-- count (DGROUP DG.key_repeat = D387, generic D69A) into its CS-relative
-- word key_repeat after every T_BDE3_000E key (mu_repeat on the mute page).
-- The cave runs at its home, CAVE_PHYS = 0x300000 + L*16 + 0x7E000 (harness
-- preamble; third PGR, XA on).  Same output as repeat_watch.lua: repeat.log
-- with one REPEAT line per store and the DGROUP key-queue capacity (QUEUE,
-- DG_SEG:DG.key_queue).  Read-only.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, iosp = cpu.spaces["program"], cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/repeat.log", "w"))

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

-- 3.16 reaches its SCSI search later than Vailixi (32.6 s instead of < 20 s).
local queue_logged = false
emu.register_periodic(function()
	if not queue_logged and machine.time:as_double() >= 33.0 and cpu.state["XA"].value ~= 0 then
		log:write(string.format("QUEUE t=%.6f capacity=%d\n", machine.time:as_double(),
			prog:read_u16(phys(DG_SEG, DG.key_queue))))
		-- The taps assume the cave runs at CAVE_PHYS: check it through the live PGR.
		if phys(CAVE_SEG, 0) ~= CAVE_PHYS then
			log:write(string.format("CAVEPHYS t=%.6f mismatch=%d\n", machine.time:as_double(), phys(CAVE_SEG, 0)))
		end
		log:flush()
		queue_logged = true
	end
end)
repeat_watch_keep_alive = taps
