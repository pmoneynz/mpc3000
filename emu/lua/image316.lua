-- Read-only observer of the WAVE316.SYS image in RAM (316 profile).
-- The harness preamble defines IMAGE_PHYS (0x300000 + L*16), CAVE_PHYS
-- (0x300000 + L*16 + 0x7E000), CAVE_SEG, CAVE_LEN.  Physical addresses hold
-- because 3.16 keeps the loader's third PGR (notes/port_316.md); each dump
-- also records the cave address through the live PGR as a check.
--
-- Env IMAGE316_AT: comma list of probe times.  At each: image316.jsonl line
-- (pool-end MOV BX,imm at image 0x48534, PGR check, write count so far),
-- cave_<t>.bin (CAVE_LEN bytes of the cave home) and head_<t>.bin (image
-- offsets 0..IMAGE316_HEAD-1, default 0x7000).
-- Env IMAGE316_WATCH_FROM: from this time on, every CPU write to image
-- offsets 0..IMAGE316_HEAD-1 is counted and the first 64 are logged to
-- image316_writes.log with PS:IP.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, iosp = cpu.spaces["program"], cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local head = tonumber(os.getenv("IMAGE316_HEAD") or "28672")
local watch_from = tonumber(os.getenv("IMAGE316_WATCH_FROM") or "1e9")
local times = {}
for t in string.gmatch(os.getenv("IMAGE316_AT") or "", "[^,]+") do times[#times + 1] = tonumber(t) end
local log = assert(io.open(out .. "/image316.jsonl", "w"))
local wlog = assert(io.open(out .. "/image316_writes.log", "w"))
local writes = 0

local function phys(seg, off)
	local a = ((seg << 4) + off) & 0xfffff
	if cpu.state["XA"].value ~= 0 then
		return ((iosp:read_u16(0xff00 + ((a >> 14) & 0x3f) * 2) & 0x3ff) << 14) | (a & 0x3fff)
	end
	return a
end

local function pc()
	local ps = cpu.state["PS"].value
	return string.format("%04X:%04X", ps, (cpu.state["CURPC"].value - (ps << 4)) & 0xffff)
end

local tap = prog:install_write_tap(IMAGE_PHYS, IMAGE_PHYS + head - 1, "image316_head",
	function(address, data, mask)
		if machine.time:as_double() < watch_from then return end
		writes = writes + 1
		if writes <= 64 then
			wlog:write(string.format("WRITE t=%.6f image=%05X data=%04X mask=%04X pc=%s\n",
				machine.time:as_double(), address - IMAGE_PHYS, data & 0xffff, mask & 0xffff, pc()))
			wlog:flush()
		end
	end)

local function dump(path, base, n)
	local f = assert(io.open(path, "wb"))
	local buf = {}
	for i = 0, n - 1 do
		buf[#buf + 1] = string.char(prog:read_u8(base + i))
		if #buf == 4096 then f:write(table.concat(buf)); buf = {} end
	end
	f:write(table.concat(buf))
	f:close()
end

local idx = 1
emu.register_periodic(function()
	if idx > #times or machine.time:as_double() < times[idx] - 0.05 then return end
	local t = times[idx]
	local imm = IMAGE_PHYS + 0x48535
	log:write(string.format('{"time":%.3f,"pool_opcode":%d,"pool_imm":%d,"cave_pgr":%d,"cave_phys":%d,"xa":%d,"writes":%d}\n',
		t, prog:read_u8(imm - 1), prog:read_u8(imm) | (prog:read_u8(imm + 1) << 8), phys(CAVE_SEG, 0), CAVE_PHYS,
		cpu.state["XA"].value, writes))
	log:flush()
	dump(string.format("%s/cave_%g.bin", out, t), CAVE_PHYS, CAVE_LEN)
	dump(string.format("%s/head_%g.bin", out, t), IMAGE_PHYS, head)
	idx = idx + 1
end)
image316_keep_alive = tap
