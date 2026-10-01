-- Read-only observation of the compiled mute-group state and UI.
-- The Python wrapper supplies exact offsets from the assembled symbol map.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, ports = cpu.spaces["program"], cpu.spaces["io"]
local out = os.getenv("PROBE_OUT")
local log = assert(io.open(out .. "/mute_ui.jsonl", "w"))
local times = {}
for t in string.gmatch(os.getenv("PROBE_TIMES") or "", "[^,]+") do
    times[#times + 1] = tonumber(t)
end
local function phys(seg, off)
    local a = ((seg << 4) + off) & 0xfffff
    if cpu.state["XA"].value ~= 0 then
        return ((ports:read_u16(0xff00 + (a >> 14) * 2) & 0x3ff) << 14) | (a & 0x3fff)
    end
    return a
end
local function rd(name)
    return prog:read_u8(phys(0xf07d, MUTE_OFFSETS[name]))
end
local index = 1
emu.register_periodic(function()
    if index > #times or machine.time:as_double() < times[index] - 0.03 then return end
    local t = times[index]
    log:write(string.format('{"time":%.3f,"program":%d,"pad":%d,"focus":%d,"active_program":%d}\n',
        t, rd("mu_program"), rd("mu_pad"), rd("mu_focus"),
        prog:read_u8(phys(0x8010, MUTE_PROGRAM_OFFSET))))
    log:flush()
    local f = assert(io.open(string.format("%s/mute_state_%.3f.bin", out, t), "wb"))
    for i = 0, 24 * 33 - 1 do
        f:write(string.char(prog:read_u8(phys(0xf07d, MUTE_OFFSETS.mute_states + i))))
    end
    f:close()
    index = index + 1
end)
dofile(MUTE_PROBE_PATH)
