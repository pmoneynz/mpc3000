; OS 3.16 boot banner (mods/WAVE316.args replaces image 0x2826..0x283D, the
; cursor at row 3 and the centred print of "System 3.16 (02/20/05)", with a
; far call here).  Two centred lines under 3.16's own "Akai MPC3000" title, on
; rows 1 and 2 (sysinfo316.inc fills rows 3-5),
; printed with the cursor and put-string routines the cave already uses.
; Placed after entry316 so no other cave offset moves.

banner316:
        mov ax, (BANNER_COL1 << 8) | 1  ; row 1
        mov bx, banner_title
        call .line
        mov ax, (BANNER_COL2 << 8) | 2  ; row 2
        mov bx, banner_version
        call .line
        retf
.line:  call du_rc
        jmp du_put

banner_title:   db "WAVEFORM/ZONES/MUTE GROUP", 0
banner_version: db "PMONEY BETA 1.0", 0
BANNER_COL1     equ (40 - (banner_version - banner_title - 1)) / 2
BANNER_COL2     equ (40 - ($ - banner_version - 1)) / 2
