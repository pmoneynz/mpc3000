-- Timestamp every write to selected DGROUP (8010:xxxx) words, for the
-- sequencer timing evidence in notes/sequencer_model.md.
--
-- Env SEQ_WATCH: comma list of name=hexoffset, e.g.
--   "pos=9232,state=D800,irq=D838,next=9242,played=76FE,held=975A"
-- Env SEQ_WATCH_FROM: emulated seconds before the taps are installed
--   (default 43; the taps need XA=1 and the final PGR table).
-- Output seq_watch.log: "<time> <name> <word written> <write mask>", one
-- line per write. A byte write shows mask 00FF or FF00. Offsets are for
-- Vailixi 3.50; the DGROUP layout differs in other OS versions.
-- Then run the normal probe.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, iosp = cpu.spaces["program"], cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/seq_watch.log", "w"))
local start = tonumber(os.getenv("SEQ_WATCH_FROM") or "43")

local function phys(seg, off)
	local a = ((seg << 4) + off) & 0xfffff
	return ((iosp:read_u16(0xff00 + ((a >> 14) & 0x3f) * 2) & 0x3ff) << 14) | (a & 0x3fff)
end

local watch = {}
for item in string.gmatch(os.getenv("SEQ_WATCH") or "", "[^,]+") do
	local name, off = string.match(item, "^([^=]+)=(%x+)$")
	watch[#watch + 1] = { name = name, off = tonumber(off, 16) }
end

local taps, installed = {}, false
emu.register_periodic(function()
	if not installed and machine.time:as_double() >= start and cpu.state["XA"].value ~= 0 then
		for _, w in ipairs(watch) do
			local p = phys(0x8010, w.off) & ~1
			taps[#taps + 1] = prog:install_write_tap(p, p + 1, "seq_" .. w.name,
				function(address, data, mask)
					log:write(string.format("%.7f %s %04X %04X\n",
						machine.time:as_double(), w.name, data & 0xffff, mask & 0xffff))
				end)
		end
		installed = true
	end
	log:flush()
end)
seq_watch_keep_alive = taps
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
