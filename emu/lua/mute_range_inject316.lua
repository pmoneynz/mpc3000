-- mute_range_inject.lua for the 316 profile (emu/test_mute_range.py): the
-- same fault injection with the same semantics.  The suite prelude defines
-- INJECT = {hook=, frame=, width=, value=, back_seg=, back_off=, staging=,
-- after=}; back_seg:back_off is the stock caller's return site as it runs
-- (CS = L + its 3.16 relative segment).  The harness preamble defines
-- CAVE_SEG and CAVE_PHYS: the cave hook runs at its home, CAVE_SEG:hook =
-- physical CAVE_PHYS + hook.  3.16 keeps the loader's third PGR, so the
-- return site's physical address is 0x300000 + logical.
--
-- When the hooked stock site enters the cave hook, the program index in the
-- caller's frame [SS:BP+frame] is replaced by `value` and the 33 staging
-- bytes are zeroed.  When control is back in the stock caller at
-- back_seg:back_off, the original index is restored and the staging bytes
-- are logged.  Hook entries before emulated time `after` are left alone.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, ports = cpu.spaces["program"], cpu.spaces["io"]
local out = os.getenv("PROBE_OUT")
local log = assert(io.open(out .. "/inject.txt", "w"))

local function phys(seg, off)
    local a = ((seg << 4) + off) & 0xfffff
    if cpu.state["XA"].value ~= 0 then
        return ((ports:read_u16(0xff00 + (a >> 14) * 2) & 0x3ff) << 14) | (a & 0x3fff)
    end
    return a
end
local function at(seg, off)
    local ps = cpu.state["PS"].value
    return ps == seg and ((cpu.state["CURPC"].value - (ps << 4)) & 0xffff) == off
end
local function staging_hex()
    local s = {}
    for i = 0, 32 do
        s[#s + 1] = string.format("%02x", prog:read_u8(phys(CAVE_SEG, INJECT.staging + i)))
    end
    return table.concat(s)
end

local slot, original, done = nil, nil, false
local function on_hook()
    if slot or done or machine.time:as_double() < INJECT.after
        or not at(CAVE_SEG, INJECT.hook) then return end
    slot = phys(cpu.state["SS"].value, (cpu.state["BP"].value + INJECT.frame) & 0xffff)
    original = prog:read_u8(slot)
    prog:write_u8(slot, INJECT.value & 0xff)
    if INJECT.width == 2 then           -- byte accesses: the slot may be odd
        original = original | (prog:read_u8(slot + 1) << 8)
        prog:write_u8(slot + 1, INJECT.value >> 8)
    end
    for i = 0, 32 do prog:write_u8(phys(CAVE_SEG, INJECT.staging + i), 0) end
    log:write(string.format("inject %.3f slot=%06X original=%d value=%d\n",
        machine.time:as_double(), slot, original, INJECT.value))
    log:flush()
end
local function on_back()
    if not slot or done or not at(INJECT.back_seg, INJECT.back_off) then return end
    prog:write_u8(slot, original & 0xff)
    if INJECT.width == 2 then prog:write_u8(slot + 1, original >> 8) end
    done = true
    log:write(string.format("restore %.3f staging=%s\n", machine.time:as_double(), staging_hex()))
    log:flush()
end

-- Opcode fetches of the two sites.
local hook_phys = CAVE_PHYS + INJECT.hook
local back_phys = 0x300000 + (((INJECT.back_seg << 4) + INJECT.back_off) & 0xfffff)
inject_taps = {
    prog:install_read_tap(hook_phys & ~1, hook_phys | 1, "inject_hook", function() on_hook() end),
    prog:install_read_tap(back_phys & ~1, back_phys | 1, "inject_back", function() on_back() end),
}
