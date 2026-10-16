; OS 3.16 System Information: port of Vailixi 3.50 B000:000E (phase 2) as one
; screen under the PMONEY banner (port spec: notes/vailixi_port.md).
; mods/WAVE316.args replaces CALLF 0955:20BF at image 0x283E, the last call of
; 3.16's banner routine 0281:000A, which the boot (image 0x2889) and Other ->
; Soft Key 3 <Version> (image 0x19EA1) both reach.  Vailixi shows its license
; screen for 5 s before this page; PMONEY keeps one screen and no delay, so
; the boot timing is unchanged.
;
; Rows 3-5: free sound memory and free sequence memory in K, with the stock
; Disk -> Load Free(snd)/Free(seq) formulas (free sound words * 2 / 1024;
; (free sequence bytes - 400) / 1024, signed, so never negative), and an
; I-0055 line when the stock port-50h probe reports the option.  The probe
; runs once, at boot, and its answer is reused: the Other-page key never
; writes port 50h while SMPTE sync may be running.  Text is PMONEY's own.
;
; Entry: DS = DGROUP, rows 0-2 drawn.  Exit: '=' rule on row 6, cursor (7,0),
; as the replaced call left it.  Preserves SI, DI, BP, DS.

sysinfo316:
        mov al, 3
        call du_at                      ; cursor row 3, column 0
        FCALL T_D0C0_0236               ; free sound words, DX:AX
        shl ax, 1
        rcl dx, 1
        call .kib
        push ax
        push cs
        push si_snd
        FCALL T_B1BC_01EE               ; row 3 (40 characters: the cursor moves to row 4)
        add sp, 6
        FCALL T_E21A_000B               ; free sequence bytes, DX:AX
        add ax, -400
        adc dx, -1
        call .kib
        push ax
        push cs
        push si_seq
        FCALL T_B1BC_01EE               ; row 4
        add sp, 6
        mov al, [cs:si_option]
        cmp al, 0xFF
        jne .known
        FCALL T_D6A0_0213               ; I-0055 probe, once
        mov [cs:si_option], al
.known: or al, al
        jz .done
        push cs
        push si_smpte
        FCALL T_B1BC_01EE               ; row 5
        add sp, 4
.done:  FCALL T_B77C_20C5               ; the replaced stock call
        retf

.kib:   push byte 0                     ; AX = DX:AX / 1024, signed
        push 0x400
        push dx
        push ax
        FCALL T_F800_20FA
        ret

si_snd:    db "Sound memory free (SND/PGM/SET):  %5uK", 0
si_seq:    db "Seq memory free (SEQ/ALL/MID):    %5uK", 0
si_smpte:  db "I-0055 SMPTE sync option:        Present", 0
si_option: db 0xFF                      ; probe result: FFh not yet probed
