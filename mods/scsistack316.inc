; Private stack for the 3.16 SCSI partition reader (PMONEY cave, PROFILE_316 only).
; Fixes a stock OS 3.16 stack overrun; not a Vailixi feature.  Evidence and
; reasoning: notes/port_316.md, "SCSI reader stack".
;
; Hook (WAVE316.args form):
;   --patch=2b017:558bec81ec0e10:ea{scsi_stack}9090                       reader prologue
;
; The reader 2AB2:04F7 (image 0x2B017, Vailixi D470:05B6) opens a 100Eh-byte
; frame (a 4 KB sector buffer at [bp-100Eh]; mnt_hybrid in diskutil316.inc reads
; into [bp-100Eh+800h] of the same frame).  It is reached through the media
; check 2033:000C (function 0) -> 2AB2:0767 and through the scan 2AB2:03A5.
; The UI task's stack is 73E1:0000..3E80 (16,000 bytes); the Disk 7 page
; 077D:042D opens a 3652h-byte frame, so with a SCSI disk active its media
; check enters the reader with SP = 07D2: SUB SP,100Eh wraps SP to F7C2 and
; the frame and its callees write 73E1:F6xx..FFFF = image 0x835xx..0x83E0F,
; above 3.16's extent (0x7DFB0) and the cave home's start (stock and PMONEY).
;
; Here the reader's frame lives on a private stack of SCSI_STK_PARAS
; paragraphs between 3.16's sequence pool and its image: entry316 lowers the
; pool end (the MOV BX,imm16 at image POOL_INIT_IMM) by SCSI_STK_PARAS, and
; this routine takes the stack only when that immediate shows the room (pool
; end + 1 + SCSI_STK_PARAS <= L), so it never runs on pool memory.  The reader
; takes no stack arguments (C far function, called PUSH CS / CALL near: AX
; result, SI/DI/BP/DS kept; AX, BX, CX, DX, ES free on entry), so only its
; return address stays on the caller's stack.  AMX saves and restores a task's
; SS:SP verbatim (47BF:0170, 019B, 01DE, 021F), so a task switch or interrupt
; while the reader runs keeps this stack.  One user at a time: scsi_stk_busy
; is taken with XCHG (one instruction: no task switch between test and set); a
; second entry while it is held (another task) runs the stock prologue on its
; own stack, as stock.
;
; Out: AX = the reader's result; flags (IF included) as on entry; ES = the
; caller's SS where the reader left it on the private stack's segment (stock:
; the body's SS far pointers leave ES = SS); every other register as the
; reader leaves it.

SCSI_STK_BYTES equ SCSI_STK_PARAS * 16  ; 109Ah measured (frame 1010h + SI/DI + callees + one IRQ entry)
SCSI_IMM_PARA  equ 0x4800               ; a paragraph below POOL_INIT_IMM that is no segment value

scsi_stack:                             ; JMPF from 2AB2:04F7 (7 bytes replaced, 2 NOPs follow)
        mov al, 1
        xchg al, [cs:scsi_stk_busy]
        test al, al
        jnz .stock                      ; held: stock prologue on the caller's stack
        mov ax, cs
        add ax, 0x10000 - CAVE_HOME     ; L (no segment-valued immediate: builder scan)
        mov dx, ax
        add ax, SCSI_IMM_PARA           ; L + 4800h
        mov es, ax
        mov ax, [es:POOL_INIT_IMM - SCSI_IMM_PARA * 16]   ; the pool-end immediate
        inc ax                          ; first paragraph above the pool
        sub dx, SCSI_STK_PARAS          ; the stack must end at or below L
        cmp ax, dx
        ja .unheld                      ; pool not lowered: stock
        mov bx, ax
        mov [cs:scsi_stk_seg], bx
        pushf
        pop word [cs:scsi_stk_flags]
        cli
        mov [cs:scsi_stk_sp], sp        ; caller's stack: return IP, CS
        mov [cs:scsi_stk_ss], ss
        mov ss, bx
        mov sp, SCSI_STK_BYTES
        push word [cs:scsi_stk_flags]
        popf                            ; IF as on entry
        push cs
        call .stock                     ; far frame: the reader's RETF comes back here
        cli
        mov ss, [cs:scsi_stk_ss]
        mov sp, [cs:scsi_stk_sp]
        mov bx, es                      ; ES left on the private stack's segment (the
        mov dx, ss                      ; body's SS far pointers) becomes the caller's
        cmp bx, [cs:scsi_stk_seg]       ; SS, as the stock body leaves it
        jne .es_kept
        mov es, dx
.es_kept:
        mov byte [cs:scsi_stk_busy], 0  ; released only after leaving the stack
        push word [cs:scsi_stk_flags]
        popf
        retf                            ; to the reader's caller
.unheld:
        mov byte [cs:scsi_stk_busy], 0
.stock:                                 ; the replaced prologue, then the reader body
        push bp
        mov bp, sp
        sub sp, 0x100E
        FJMP T_D470_05BD

scsi_stk_busy:  db 0
align 2
scsi_stk_flags: dw 0
scsi_stk_sp:    dw 0
scsi_stk_ss:    dw 0
scsi_stk_seg:   dw 0
