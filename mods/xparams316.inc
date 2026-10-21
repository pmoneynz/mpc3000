; OS 3.16: Vailixi 3.50's "Extra System Parameters" (Other -> Soft Key 4) and
; real-time sample editing, ported to PMONEY (port spec: notes/vailixi_port.md).
;
; Settings live in 3.16's zeroed 13-byte reserve at the end of the system
; parameter block (DS 8316..8322; Vailixi used 8628..862F of its own block),
; so the stock code already saves them to NVRAM and .PAR files.  Each byte
; holds (shown value) XOR (Vailixi default): the stock zero-fill (Init PAR,
; a failed NVRAM checksum, any 3.12/3.16 .PAR) then gives Vailixi's defaults.
;
;   XP_SND_STOP    OFF  stop all voices when STOP ends a run (Vailixi DE5C:05A8)
;   XP_WARN        ON   seq change while running in record-ready: warn, stop
;                       and switch (stock); OFF: refuse (Vailixi C303:0373)
;   XP_STAY_EDIT   OFF  PLAY / PLAY START keep Edit Sound open (DE5C:02CF)
;   XP_STAY_MIXER  OFF  PLAY / PLAY START keep Mixer pages 1-6 open (DE5C:02B3)
;   XP_MUTE_EDIT   ON   port 6Ah mute around the Edit Sound processes
;   XP_SAFE_LOCK   ON   Edit Sound Do refused while the transport runs
;                       (wave_chop.inc chop_do_dispatch, CHOP_HAS_SAFE_LOCK)
;
; Real-time editing (Vailixi F4 + D1): WAVE316.args removes the transport stop
; the Program/Sounds 6 arm makes before Edit Sound (image 0x1A056), and wraps
; the seven Edit Sound wave transfers in the playback lock (xp_xfer_locked).
; Screen text is PMONEY's own.

; ---------------------------------------------------------------- audio mute

; Near.  AL = 1 mutes, 0 unmutes: OUT 6Ah, 00h / 0Eh with IF clear, as
; Vailixi D980:000C (3.16's own 2FAB:000E is the same without PUSHF/CLI).
; Keeps every register but AL and flags.
xp_audio:
        pushf
        cli
        cmp al, 1
        mov al, 0x00
        je .out
        mov al, 0x0E
.out:   out 0x6A, al
        popf
        ret

; Near.  Mute / unmute if "mute during sound edits" is ON (byte 0).  Keep
; every register and the flags' consumers: callers rely on AX afterwards.
xp_mute_if:
        push ax
        mov al, 1
        jmp xp_mute_common
xp_unmute_if:
        push ax
        mov al, 0
xp_mute_common:
        cmp byte [XP_MUTE_EDIT], 0
        jne .skip
        call xp_audio
.skip:  pop ax
        ret

; ---------------------------------------------------------------- Other page

; FAR from 19D0:0126 (image 0x19E26): the soft-key row, with <Extra> added.
xp_other_keys:
        mov bx, xp_s_keys
        call du_put
        retf

; JMP from 19D0:0160 (image 0x19E60), DX = normalized key (non-zero).
xp_other_dispatch:
        cmp dx, 0x75                    ; Soft Key 4
        jne .stock
        call xp_extra_screen
        mov dx, ax
        FJMP T_C84C_01DB                ; or dx,dx / jnz return / key loop
.stock: mov bx, dx                      ; the replaced instructions
        sub bx, 0x75
        FJMP T_C84C_016D                ; cmp bx,5 / dispatch table

; Near.  The Extra Settings pages: OFF/ON choice fields, <More> / <Back>
; (Soft Key 4) flips between page 1 (xp_rows) and page 2 (xp_rows2), <Do it>
; (Soft Key 1) returns the play-screen mode [XP_PLAY_SCREEN], any other key
; that leaves the field editor is returned.  AX = key or mode.
xp_extra_screen:
        push si
        mov byte [cs:xp_page], 0
.page:  mov bx, xp_s_title
        mov si, xp_rows
        cmp byte [cs:xp_page], 0
        je .titled
        mov bx, xp_s_title2
        mov si, xp_rows2
.titled:
        call du_title
.row:   mov al, [cs:si]                 ; row number, 0 ends
        or al, al
        jz .rows_done
        call du_at
        push byte 3
        cmp byte [cs:si+1], 0           ; polarity: 0 direct, 1 inverted
        jne .inverted
        push ds
        push XP_OFF_ON
        jmp .table
.inverted:
        push cs
        push xp_on_off
.table: push ds
        push word [cs:si+2]             ; the setting's DS offset
        push cs
        push word [cs:si+4]             ; label
        FCALL T_B354_01C6
        add sp, 14
        add si, 6
        jmp .row
.rows_done:
        mov al, 7
        mov bx, xp_s_more
        cmp byte [cs:xp_page], 0
        je .keys
        mov bx, xp_s_doit2
.keys:  call du_row_put
.key:   push byte 4                     ; low 3 bits: soft keys 1-4 leave the editor
        FCALL T_B060_035D
        add sp, 2
        or al, al
        jz .key
        cmp al, 0x79                    ; Soft Keys 2 and 3 do nothing here
        je .key
        cmp al, 0x7A
        je .key
        cmp al, 0x75                    ; Soft Key 4: the other page
        jne .not_page
        xor byte [cs:xp_page], 1
        jmp .page
.not_page:
        cmp al, 0x78                    ; Soft Key 1 <Do it>
        jne .leave
        mov al, [XP_PLAY_SCREEN]
.leave: cbw
        pop si
        ret

; ---------------------------------------------------------------- transport

; JMP from 148A:0379 (image 0x14C19), the stock stop + warning + switch after
; a sequence change while running with [XP_SEQ_STATE] != 1.
xp_seq_warn:
        cmp byte [XP_SEQ_STATE], 0
        jne .refuse
        cmp byte [XP_WARN], 0           ; 0 = ON
        jne .refuse
        FCALL T_E704_0007               ; the replaced call: stop the transport
        FJMP T_C303_0386                ; stock warning box and switch
.refuse:
        FJMP T_C303_03B4                ; the field reverts, the transport runs on

; JMP from 3481:02BD (image 0x34ACD), the key filter's 'Q' case after PLAY or
; PLAY START, past the stock mode 'K' 10..15 test.
xp_play_stay:
        cmp byte [cs:tm_owned], 0       ; Track Mute stays open while
        jne .stay                       ; the sequence plays (trackmute316.inc)
        cmp byte [XP_STAY_MIXER], 0
        je .edit
        cmp byte [MODE], 'J'
        jne .edit
        cmp byte [OPTION], 6            ; Mixer pages 1-5 and Input Thru
        jg .edit
        jmp .stay
.edit:  cmp byte [XP_STAY_EDIT], 0
        je .stock
        cmp byte [MODE], 'L'
        jne .stock
        cmp byte [OPTION], 6
        jne .stock
.stay:  mov byte [bp+6], 0              ; consumed: the screen stays
        FJMP T_DE5C_087D
.stock: cmp byte [MODE], 'S'            ; the replaced compare; its JNZ follows
        FJMP T_DE5C_02F0

; JMP from 3481:0571 (image 0x34D81), the key filter's STOP case after the
; post-stop work of a run.
xp_stop_snd:
        mov byte [XP_POST_STOP], 1      ; the replaced instructions
        dec byte [BUSY]
        cmp byte [XP_SND_STOP], 0
        je .done
        FCALL T_CFC6_0D93               ; stop all 32 voices
        mov al, 0
        call xp_audio                   ; and unmute, as Vailixi
.done:  FJMP T_DE5C_05BE

; ---------------------------------------------------------------- Edit Sound mute

; Copy wrapper 0B72:1398 (Do COPY ZONE-> TEMP): mute at entry, unmute on
; both exits.
xp_copy_entry:
        call xp_mute_if
        push ds                         ; the replaced instructions
        push EDITDO_TEMP_NAME
        FCALL T_D0C0_0D17
        FJMP T_B99A_175E                ; add sp,4
xp_copy_check:
        mov [bp-1], al                  ; the replaced test of the allocation
        or al, al                       ; (= cmp al,0 / jge; JGE's 7D 07 would read as segment 077D)
        jns .ok
        call xp_unmute_if
        cbw                             ; the stock failure tail (image 0xCB25)
        pop si
        leave
        retf
.ok:    FJMP T_B99A_17A7
xp_copy_done:
        call xp_unmute_if
        xor ax, ax
        pop si
        leave
        retf

; Insert (Do 2, 3), reverse (9), silence (8), delete (4-7): mute after the
; routine's own early exits, unmute before its epilogue.
xp_ins_mute:
        call xp_mute_row7
        FJMP T_B99A_1A05                ; after the replaced cursor (7,0) and its add sp,4
xp_ins_done:
        call xp_unmute_if
        xor ax, ax
        pop di
        pop si
        leave
        retf
xp_rev_mute:
        call xp_mute_row7
        FJMP T_B99A_1E5C
xp_sil_mute:
        call xp_mute_row7
        FJMP T_B99A_215E
xp_del_mute:
        call xp_mute_row7
        FJMP T_B99A_2301
; Mute if set, then the replaced cursor (7,0).  Changes AX and flags.
xp_mute_row7:
        call xp_mute_if
        mov al, 7
        jmp du_at

; The replaced redraw of the Edit Sound soft-key row, unmute, then the three
; routines' common epilogue (0B72:1BD9 = 1DED = 2120: pop di / pop si / leave /
; retf).  AX at the RETF is the put's, as in stock.
xp_rev_done:
xp_sil_done:
xp_del_done:
        mov bx, EDITDO_SOFTKEYS
        call du_put_ds
        call xp_unmute_if
        pop di
        pop si
        leave
        retf

; ---------------------------------------------------------------- playback lock

; FAR, in place of CALLF T_CF92_000C at the seven Edit Sound wave transfers
; (Vailixi wraps the same seven in inc/dec [9757]): the playback task defers
; its ticks while BUSY is non-zero, so a transfer and playback never overlap.
; Same arguments (seven words, caller pops) and result.
xp_xfer_locked:
        push bp
        mov bp, sp
        inc byte [BUSY]
        push word [bp+18]
        push word [bp+16]
        push word [bp+14]
        push word [bp+12]
        push word [bp+10]
        push word [bp+8]
        push word [bp+6]
        FCALL T_CF92_000C
        add sp, 14
        dec byte [BUSY]
        pop bp
        retf

; ---------------------------------------------------------------- data

; Per row: row, polarity (1 = stored inverted), DS offset, label.
xp_rows:
        db 1, 0
        dw XP_SND_STOP, xp_s_snd_stop
        db 2, 1
        dw XP_WARN, xp_s_warn
        db 3, 0
        dw XP_STAY_EDIT, xp_s_stay_edit
        db 4, 0
        dw XP_STAY_MIXER, xp_s_stay_mixer
        db 5, 1
        dw XP_MUTE_EDIT, xp_s_mute
        db 6, 1
        dw XP_SAFE_LOCK, xp_s_lock
        db 0

; Inverted choice list: byte 0 shows ON, 1 shows OFF (the stock strings).
xp_on_off:
        dw XP_STR_ON, DGROUP_SEG
        RELOC_PREV
        dw XP_STR_OFF, DGROUP_SEG
        RELOC_PREV
        dd 0

xp_s_keys:       db "<Init PAR><Rec 16 Chs><Version>  <Extra>", 0
xp_s_title:      db "Extra Settings", 0
xp_s_snd_stop:   db "Stop all sounds on sequencer STOP:   ", 0
xp_s_warn:       db "Allow seq change while running:      ", 0   ; ON: warn, stop, switch; OFF: change refused
xp_s_stay_edit:  db "Stay in Edit Sound on PLAY/START:    ", 0
xp_s_stay_mixer: db "Stay in Mixer on PLAY/START:         ", 0
xp_s_mute:       db "Mute outputs during sound edits:     ", 0
xp_s_lock:       db "Lock Edit Sound <Do> while running:  ", 0
