-- Replace the floppy during the run, then run snddump.lua (which runs the
-- normal probe). FLOP_SWAP is "t=path" or several "t=path" joined by ';',
-- in ascending emulated time t (s). MAME writes a modified image back when
-- it is replaced or when MAME exits.
local machine = manager.machine
local swaps = {}
for t, path in string.gmatch(os.getenv("FLOP_SWAP") or "", "([%d%.]+)=([^;]+)") do
	swaps[#swaps + 1] = {tonumber(t), path}
end
local next_swap = 1
emu.register_periodic(function()
	local swap = swaps[next_swap]
	if not swap or machine.time:as_double() < swap[1] then return end
	next_swap = next_swap + 1
	for tag, image in pairs(machine.images) do
		if string.find(tag, "fdc") then
			local err = image:load(swap[2])
			if err then error("flop_swap: " .. tostring(err)) end
		end
	end
end)
dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "snddump.lua")
