-- LCD mirror test (emu/test_lcdmirror316.py): logs 3.16's BIOS cursor word
-- (59FA:68AB, physical LM_CURSOR_PHYS) and the OS cursor-mode byte (DGROUP 1D02,
-- LM_CMODE_PHYS) whenever either changes, sampled at every periodic callback (each emulated frame).
-- Writes lcdmirror_watch.txt in PROBE_OUT: "t cursor mode" (hex).  Read-only.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local out = os.getenv("PROBE_OUT") or "."
local cur_phys = tonumber(os.getenv("LM_CURSOR_PHYS"), 16)
local mode_phys = tonumber(os.getenv("LM_CMODE_PHYS"), 16)
local log = io.open(out .. "/lcdmirror_watch.txt", "w")
local last = nil
local function sample()
	local c = prog:read_u16(cur_phys)
	local m = prog:read_u8(mode_phys)
	local key = c * 256 + m
	if key ~= last then
		last = key
		log:write(string.format("%.6f %04X %02X\n", machine.time:as_double(), c, m))
		log:flush()
	end
end
emu.register_periodic(sample)
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
