; S1a fast exact 32-bit divide (notes/performance.md sections 9 and 12).
; Included by mods/s1a.asm (Vailixi 3.50 Route A; runtime in the BIOS at
; F800:20FA / 2101) and by the PMONEY cave under PROFILE_316 (3.16's own
; linked copy of the same runtime, relative 0009:20F6 / 20FD).  The includer
; defines FJMP and S1A_IDIV_RUNTIME / S1A_UDIV_RUNTIME.  Contract and proof:
; mods/s1a.asm.

s1a_idiv:                               ; replaces CALLF F800:20FA
        push bp
        mov bp, sp
        mov bx, [bp+10]                 ; divisor low
        cmp word [bp+12], 0
        jne .runtime
        or bx, bx
        jz .runtime
        mov ax, [bp+6]
        mov dx, [bp+8]
        mov cx, dx                      ; CX bit 15: dividend sign = quotient sign
        or dx, dx
        jns .divide
        neg dx
        neg ax
        sbb dx, 0
.divide:
        xchg ax, dx                     ; AX = high, DX = low
        mov [bp+12], dx
        xor dx, dx
        div bx                          ; AX = quotient high, DX = remainder
        xchg ax, [bp+12]                ; AX = low, slot = quotient high
        div bx                          ; AX = quotient low
        mov dx, [bp+12]
        or cx, cx
        jns .done
        neg dx
        neg ax
        sbb dx, 0
.done:
        pop bp
        retf 8
.runtime:
        pop bp
        FJMP S1A_IDIV_RUNTIME

s1a_udiv:                               ; replaces CALLF F800:2101
        push bp
        mov bp, sp
        mov bx, [bp+10]
        cmp word [bp+12], 0
        jne .runtime
        or bx, bx
        jz .runtime
        mov ax, [bp+8]                  ; AX = high
        xor dx, dx
        div bx
        mov [bp+12], ax                 ; quotient high
        mov ax, [bp+6]                  ; DX = remainder, AX = low
        div bx
        mov dx, [bp+12]
        pop bp
        retf 8
.runtime:
        pop bp
        FJMP S1A_UDIV_RUNTIME
