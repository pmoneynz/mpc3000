; Timing Correct: Vailixi 3.50's 13 note values on OS 3.16 (PMONEY cave, PROFILE_316 only).
; Port spec: notes/vailixi_port.md.  Hooks: mods/WAVE316.args (timing correct).
;
; Model.  TC_EXT (DGROUP 67DB, freed TC table space, NOT persisted) holds the
; Vailixi index 0..12.  TC_NOTE (3.16 [7EBD], parameter block +25Ch, persisted
; in NVRAM page 61 and .PAR files shared with every stock OS) always holds the
; stock index 0..6 = TC_PROJ[TC_EXT].  The TC screen field edits TC_EXT; its
; field-0/1 handler (in place at 1FA0:0215) writes TC_NOTE = TC_PROJ[TC_EXT].
; Every other writer of TC_NOTE (defaults, NVRAM restore, .PAR load in both
; formats, the parameter-reset menu) is followed by the apply routine 0F78:0136,
; which calls the grid 1FA0:0442, which calls tc_grid_interval: if TC_EXT does
; not project onto TC_NOTE, TC_EXT := TC_CANON[TC_NOTE].

; CALLF from the grid 1FA0:0442 (Vailixi CE7A:042C), replacing
;   MOV AL,[7EBD] / CBW / MOV BX,AX / MOV AL,[BX+67A2]   (10 bytes; 5 NOPs follow the CALLF)
; In: DS = DGROUP (the grid's own contract).  Out: AL = interval in ticks.
; Clobbers AH, BX, flags (the replaced bytes clobbered AX and BX; the grid
; reloads BX and AH before use).  Stack: 4 bytes.  Not called from an ISR.
tc_grid_interval:
        mov bl, [TC_EXT]
        cmp bl, 12
        ja .resync
        xor bh, bh
        mov al, [bx+TC_PROJ]
        cmp al, [TC_NOTE]
        je .ok
.resync:
        mov bl, [TC_NOTE]
        cmp bl, 6
        jbe .canon
        mov byte [TC_NOTE], 3           ; not a stock index (foreign NVRAM): stock reset 1/16
        mov byte [TC_NV_DIRTY], 1
        mov bl, 3
.canon:
        xor bh, bh
        mov bl, [bx+TC_CANON]
        mov [TC_EXT], bl
.ok:
        xor bh, bh
        mov al, [bx+TC_TICKS]
        retf

%ifdef TC_REPEAT_GATE
; JMPF from the playback tick 422F:02B9 (Vailixi EC05:02A9), replacing
;   CMP BYTE [A4A2],0 / JZ 02D8   (7 bytes; 2 NOPs follow the JMPF)
; Vailixi adds "index > 2" here; with TC_NOTE = TC_PROJ[TC_EXT] that is TC_NOTE != 0.
; In: DS = DGROUP, playback task.  Uses flags only.  Stack untouched.
tc_repeat_gate:
        cmp byte [TC_HELD], 0
        je .skip
        cmp byte [TC_NOTE], 0
        je .skip
        FJMP T_EC05_02B0                ; 422F:02C0  CMP BYTE [95C8],0 (drum or MIDI repeat)
.skip:
        FJMP T_EC05_02C8                ; 422F:02D8  MOV AX,[86EE] (record-flush arm)
%endif

; Labels, 10 characters (the field width).  Note values keep the stock
; label scheme; the three OFF resolutions are PMONEY's own wording.
tc_lbl_0:  db "OFF 128th ", 0
tc_lbl_1:  db "OFF 192nd ", 0
tc_lbl_2:  db "OFF 384th ", 0
tc_lbl_3:  db "1/4 NOTE  ", 0
tc_lbl_4:  db "1/4 TRPLT ", 0
tc_lbl_5:  db "1/8 NOTE  ", 0
tc_lbl_6:  db "1/8 TRPLT ", 0
tc_lbl_7:  db "1/16 NOTE ", 0
tc_lbl_8:  db "1/16 TRPLT", 0
tc_lbl_9:  db "1/32 NOTE ", 0
tc_lbl_10: db "1/32 TRPLT", 0
tc_lbl_11: db "1/64 NOTE ", 0
tc_lbl_12: db "1/64 TRPLT", 0
