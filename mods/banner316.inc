; OS 3.16 boot banner (mods/WAVE316.args replaces image 0x2826..0x283D, the
; cursor at row 3 and the centred print of "System 3.16 (02/20/05)", with a
; far call here).  Two centred lines under 3.16's own "Akai MPC3000" title,
; printed with the cursor and put-string routines the cave already uses.
; Placed after entry316 so no other cave offset moves.

banner316:
        push BANNER_COL1                ; column
        push 3                          ; row
        FCALL T_B1B1_0026
        add sp, 4
        push strict word CAVE_SEG
        RELOC_PREV
        push banner_title
        FCALL T_B1B1_005B
        add sp, 4
        push BANNER_COL2
        push 4
        FCALL T_B1B1_0026
        add sp, 4
        push strict word CAVE_SEG
        RELOC_PREV
        push banner_version
        FCALL T_B1B1_005B
        add sp, 4
        retf

banner_title:   db "WAVEFORM/ZONES/MUTE GROUP", 0
banner_version: db "PMONEY BETA 1.0", 0
BANNER_COL1     equ (40 - (banner_version - banner_title - 1)) / 2
BANNER_COL2     equ (40 - ($ - banner_version - 1)) / 2
