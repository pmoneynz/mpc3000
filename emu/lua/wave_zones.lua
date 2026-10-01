-- The test wrapper defines WAVE_ZONE_OFFSETS from the assembled symbol map.
-- Observe the real RAM payload and sound data; do not seed firmware state.
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
local function byte(name) return prog:read_u8(phys(0xf07d, WAVE_ZONE_OFFSETS[name])) end
local next_time = 1
emu.register_periodic(function()
    if next_time > #times or machine.time:as_double() < times[next_time] - 0.05 then return end
    log:write(string.format('{"time":%.3f,"valid":%d,"current":%d,"count":%d,"focus":%d,"sel":%d,"zoom":%d,"bounds":[',
        times[next_time], byte("zones_valid"), byte("zones_current"), byte("zones_count"), byte("onview"), byte("sel"),
        prog:read_u16(phys(0xf07d, WAVE_ZONE_OFFSETS.zoom))))
    for i = 0, 16 do
        if i > 0 then log:write(",") end
        log:write(prog:read_u32(phys(0xf07d, WAVE_ZONE_OFFSETS.zones_bounds + i * 4)))
    end
    log:write("]}\n")
    log:flush()
    local records = assert(io.open(string.format("%s/records_%.0f.bin", out, times[next_time]), "wb"))
    for i = 0, 128 * 0x24 - 1 do
        records:write(string.char(prog:read_u8(phys(0xa2ae, 0x4800 + i))))
    end
    records:close()
    next_time = next_time + 1
end)
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "snddump.lua")
