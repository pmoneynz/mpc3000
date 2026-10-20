; SCSI startup stage 1: lives in the EPROM's OS-code FF fill (mods/build_scsiboot.py).
;
; The patched loader calls this instead of the stock SYS hand-off, for both
; devices, with the loader's frame live in SS:BP (device in [BP+6]) and the
; found name's far pointer on the stack, as the hand-off expects.
;
;   device 0 (floppy): tail-jump to the stock hand-off, frame unchanged.
;   device 1 (SCSI):   INT 45 the file to STAGE2_SEG:0 through the running OS's
;                      INT 41 -> INT 40 SCSI hook.  If it carries the SCSIBOOT
;                      magic, far-call it (ABI below).  On AX=1 restore the
;                      BIOS INT 40 vector the OS hook saved at DGROUP SAVED40
;                      and tail-jump to the stock hand-off; otherwise return
;                      to the loader, which continues with APS/PGM/ALL.
;
; Stage-2 ABI 1, entry: CS=ES=STAGE2_SEG+e_cs, DS:DX = name, AX = this EPROM's
; hand-off load segment, CX = 1, IF=1, second PGR, OS running.  Exit (RETF):
; BP/SP/SS preserved, AX = 1 ready (INT 41 now served from RAM) or 0.
;
; Defines: HANDOFF_SEG, HANDOFF_OFF, LOAD_SEG, SAVED40, STAGE2_SEG.

        bits 16
        cpu 8086
        org 0

stage1:
        cmp word [bp+6], 0              ; loader's device argument (SS:BP)
        jne .scsi
        jmp HANDOFF_SEG:HANDOFF_OFF

.scsi:
        push bp
        mov bp, sp
        push ds                         ; [bp-2] = DGROUP
        push es
        push si
        push di
        lds dx, [bp+6]                  ; found name
        mov ax, STAGE2_SEG
        mov es, ax
        int 45h                         ; ES:BX entry; DS:DX restored
        or ah, ah
        jnz .fail
        push ds
        push cs
        pop ds
        mov si, magic
        xor di, di                      ; ES:0000 = start of the stage-2 image
        mov cx, 8
        cld
        repe cmpsb
        pop ds
        jne .fail
        mov ax, LOAD_SEG
        mov cx, 1
        push cs
        mov si, .back
        push si
        push es
        push bx
        retf                            ; far call ES:BX
.back:
        cmp ax, 1
        jne .fail
        mov ds, [bp-2]
        xor ax, ax
        mov es, ax
        cli                             ; the hand-off keeps IF=0 until its stack switch
        mov ax, [SAVED40]
        mov [es:0100h], ax
        mov ax, [SAVED40+2]
        mov [es:0102h], ax
        pop di
        pop si
        pop es
        pop ds
        pop bp
        jmp HANDOFF_SEG:HANDOFF_OFF

.fail:
        pop di
        pop si
        pop es
        pop ds
        pop bp
        retf

magic   db 'SCSIBOOT'
