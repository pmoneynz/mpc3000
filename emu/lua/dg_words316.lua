-- dg_words for the 316 profile (WAVE316.SYS on OS 3.16, Route C).
-- The harness preamble (emu/harness.py observer()) defines DG_PHYS, the
-- physical address of DGROUP offset 0 (0x300000 + (L+609C)*16: 3.16 keeps
-- the loader's third PGR, notes/port_316.md).  At each probe time (env
-- DG_WORDS_TIMES, default PROBE_TIMES) writes one line to dg_words.log:
--   t=<time> <off>=<byte> ...
-- for every hex DGROUP offset of env DG_BYTES (comma list), read as bytes.
-- Unlike probe.lua's PROBE_WORDS it does not guess DS from a histogram.
-- Installs no taps and never writes MPC RAM.
local machine = manager.machine
local prog = machine.devices[":maincpu"].spaces["program"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/dg_words.log", "w"))
local offsets, times = {}, {}
for v in string.gmatch(os.getenv("DG_BYTES") or "", "[^,]+") do
	offsets[#offsets + 1] = tonumber(v, 16)
end
for v in string.gmatch(os.getenv("DG_WORDS_TIMES") or os.getenv("PROBE_TIMES") or "", "[^,]+") do
	times[#times + 1] = tonumber(v)
end
local index = 1
emu.register_periodic(function()
	if index > #times or machine.time:as_double() < times[index] then return end
	local fields = {}
	for _, off in ipairs(offsets) do
		fields[#fields + 1] = string.format("%04X=%02X", off, prog:read_u8(DG_PHYS + off))
	end
	log:write(string.format("t=%g %s\n", times[index], table.concat(fields, " ")))
	log:flush()
	index = index + 1
end)
