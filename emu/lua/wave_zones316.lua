-- wave_zones.lua for the 316 profile (WAVE316.SYS on OS 3.16, Route C).
-- The harness preamble (emu/harness.py observer()) defines CAVE (assembled
-- map offsets), CAVE_SEG (runtime cave segment L+7E00) and SND_SEG (runtime
-- sound segment L+539D, records at +4800).  Same output as wave_zones.lua:
-- zones.jsonl (plus "mode": 0 Equal Division, 1 CHOPS) and records_<t>.bin.  Read-only.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, ioport = cpu.spaces["program"], cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/zones.jsonl", "w"))
local times = {}
for t in string.gmatch(os.getenv("PROBE_TIMES") or "", "[^,]+") do
    times[#times + 1] = tonumber(t)
end
local function phys(seg, off)
    local a = ((seg << 4) + off) & 0xfffff
    if cpu.state["XA"].value ~= 0 then
        return ((ioport:read_u16(0xff00 + (a >> 14) * 2) & 0x3ff) << 14) | (a & 0x3fff)
    end
    return a
end
local function byte(name) return prog:read_u8(phys(CAVE_SEG, CAVE[name])) end
local next_time = 1
emu.register_periodic(function()
    if next_time > #times or machine.time:as_double() < times[next_time] - 0.05 then return end
    log:write(string.format('{"time":%.3f,"valid":%d,"current":%d,"count":%d,"focus":%d,"sel":%d,"zoom":%d,"bounds":[',
        times[next_time], byte("zones_valid"), byte("zones_current"), byte("zones_count"), byte("onview"), byte("sel"),
        prog:read_u16(phys(CAVE_SEG, CAVE.zoom))))
    -- 3.16 keeps {start, end} pairs (wave_zones.inc, Lazy Chop): boundary i of an
    -- Equal Division is pair i's start (pair N's start is kept equal to pair N-1's end).
    for i = 0, 16 do
        if i > 0 then log:write(",") end
        log:write(prog:read_u32(phys(CAVE_SEG, CAVE.zones_pairs + i * 8)))
    end
    log:write(string.format('],"mode":%d}\n', byte("zones_mode")))
    log:flush()
    local records = assert(io.open(string.format("%s/records_%g.bin", out, times[next_time]), "wb"))
    for i = 0, 128 * 0x24 - 1 do
        records:write(string.char(prog:read_u8(phys(SND_SEG, 0x4800 + i))))
    end
    records:close()
    next_time = next_time + 1
end)
