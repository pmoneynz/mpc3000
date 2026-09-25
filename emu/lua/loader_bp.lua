-- Log which floppy-loader call sites fire (notes/floppy_loader.md §1).
-- Run with extra=["-debug", "-debugger", "none", "-log", "-autoboot_script", <this file>].
local dbg = manager.machine.debugger
for _, a in ipairs({ "b013b", "b014c", "b0171", "b0184" }) do
	dbg:command("bpset " .. a .. ",1,{logerror \"BP " .. a .. " t=%d\\n\",0; g}")
end
dbg:command("g")
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")
